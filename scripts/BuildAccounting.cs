using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

public static class BuildAccounting
{
    [StructLayout(LayoutKind.Sequential)]
    struct StartupInfo
    {
        public int cb;
        public IntPtr reserved, desktop, title;
        public int x, y, xSize, ySize, xChars, yChars, fill, flags;
        public short show, reservedSize;
        public IntPtr reservedBytes, stdin, stdout, stderr;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct ProcessInfo { public IntPtr process, thread; public uint pid, tid; }
    [StructLayout(LayoutKind.Sequential)]
    struct Accounting
    {
        public long user, kernel, periodUser, periodKernel;
        public uint faults, totalProcesses, activeProcesses, terminatedProcesses;
        public ulong readOps, writeOps, otherOps, readBytes, writeBytes, otherBytes;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct BasicLimits
    {
        public long processTime, jobTime;
        public uint flags;
        public UIntPtr minimum, maximum;
        public uint activeLimit;
        public UIntPtr affinity;
        public uint priority, scheduling;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct IoCounters { public ulong readOps, writeOps, otherOps, readBytes, writeBytes, otherBytes; }
    [StructLayout(LayoutKind.Sequential)]
    struct ExtendedLimits
    {
        public BasicLimits basic;
        public IoCounters io;
        public UIntPtr processMemory, jobMemory, peakProcessMemory, peakJobMemory;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool CreateProcess(string application, StringBuilder command, IntPtr processAttributes,
        IntPtr threadAttributes, bool inherit, uint flags, IntPtr environment, string directory,
        ref StartupInfo startup, out ProcessInfo process);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool GetExitCodeProcess(IntPtr process, out uint code);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool QueryInformationJobObject(IntPtr job, int type, out Accounting info, int length, IntPtr returned);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool TerminateProcess(IntPtr process, uint code);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool SetInformationJobObject(IntPtr job, int type, ref ExtendedLimits limits, int length);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool TerminateJobObject(IntPtr job, uint code);
    [DllImport("kernel32.dll")]
    static extern bool CloseHandle(IntPtr handle);

    public sealed class Result
    {
        public double WallSeconds, UserSeconds, KernelSeconds, CpuSeconds, AverageCores;
        public uint ExitCode, ProcessId, TotalProcesses, ActiveProcessesAtBuildExit;
        public ulong ReadBytes, WriteBytes;
        public string StartedAt, FinishedAt;
    }

    public static Result Run(string executable, string arguments, string directory, string log)
    {
        return RunCore(executable, arguments, directory, log, false);
    }

    public static Result RunOwned(string executable, string arguments, string directory, string log)
    {
        return RunCore(executable, arguments, directory, log, true);
    }

    static Result RunCore(string executable, string arguments, string directory, string log, bool owned)
    {
        // cmd supplies the same combined stdout/stderr file without a pipe reader affecting timing.
        foreach (string value in new[] { executable, arguments, directory, log })
            if (value.IndexOfAny(new[] { '\r', '\n', '%', '!' }) >= 0)
                throw new ArgumentException("Unsupported shell expansion character in measurement input.");
        if (executable.Contains("\"") || log.Contains("\""))
            throw new ArgumentException("Executable/log paths cannot contain quotes.");
        string cmd = Environment.GetEnvironmentVariable("ComSpec");
        var command = new StringBuilder("\"" + cmd + "\" /d /s /c \"\"" + executable + "\" " +
            arguments + " > \"" + log + "\" 2>&1\"");
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        if (job == IntPtr.Zero) throw new Win32Exception();
        ProcessInfo process = default;
        bool resumed = false;
        try
        {
            if (owned)
            {
                var limits = new ExtendedLimits();
                limits.basic.flags = 0x2000; // Kill only this invocation's descendants on job close.
                if (!SetInformationJobObject(job, 9, ref limits, Marshal.SizeOf<ExtendedLimits>()))
                    throw new Win32Exception();
            }
            var startup = new StartupInfo { cb = Marshal.SizeOf<StartupInfo>() };
            if (!CreateProcess(cmd, command, IntPtr.Zero, IntPtr.Zero, false, 0x08000004,
                IntPtr.Zero, directory, ref startup, out process))
                throw new Win32Exception();
            // Assignment while suspended includes every descendant, even short-lived compiler processes.
            if (!AssignProcessToJobObject(job, process.process)) throw new Win32Exception();
            var result = new Result { ProcessId = process.pid, StartedAt = DateTimeOffset.Now.ToString("o") };
            var watch = Stopwatch.StartNew();
            if (ResumeThread(process.thread) == uint.MaxValue) throw new Win32Exception();
            resumed = true;
            if (WaitForSingleObject(process.process, uint.MaxValue) != 0) throw new Win32Exception();
            watch.Stop();
            string finishedAt = DateTimeOffset.Now.ToString("o");
            if (!GetExitCodeProcess(process.process, out uint exitCode)) throw new Win32Exception();
            // Build completion is the boundary; idle compiler servers can outlive their caller.
            if (!QueryInformationJobObject(job, 8, out Accounting accounting, Marshal.SizeOf<Accounting>(), IntPtr.Zero))
                throw new Win32Exception();
            result.FinishedAt = finishedAt;
            result.ExitCode = exitCode;
            result.WallSeconds = watch.Elapsed.TotalSeconds;
            result.UserSeconds = accounting.user / 10000000.0;
            result.KernelSeconds = accounting.kernel / 10000000.0;
            result.CpuSeconds = result.UserSeconds + result.KernelSeconds;
            result.AverageCores = result.CpuSeconds / result.WallSeconds;
            result.TotalProcesses = accounting.totalProcesses;
            result.ActiveProcessesAtBuildExit = accounting.activeProcesses;
            result.ReadBytes = accounting.readBytes;
            result.WriteBytes = accounting.writeBytes;
            return result;
        }
        finally
        {
            if (owned && resumed)
            {
                // The build clock has stopped. Drain resident compiler servers before the next phase.
                try
                {
                    if (!TerminateJobObject(job, 1)) throw new Win32Exception();
                    bool drained = false;
                    for (int attempt = 0; attempt < 100; attempt++)
                    {
                        if (!QueryInformationJobObject(job, 8, out Accounting active, Marshal.SizeOf<Accounting>(), IntPtr.Zero))
                            throw new Win32Exception();
                        if (active.activeProcesses == 0) { drained = true; break; }
                        System.Threading.Thread.Sleep(100);
                    }
                    if (!drained) throw new InvalidOperationException("Owned build descendants did not drain.");
                }
                finally
                {
                    if (process.thread != IntPtr.Zero) CloseHandle(process.thread);
                    if (process.process != IntPtr.Zero) CloseHandle(process.process);
                    CloseHandle(job);
                }
            }
            else
            {
                // Only an unstarted process created by this call may be terminated on setup failure.
                if (!resumed && process.process != IntPtr.Zero && !TerminateProcess(process.process, 1))
                    throw new Win32Exception();
                if (process.thread != IntPtr.Zero) CloseHandle(process.thread);
                if (process.process != IntPtr.Zero) CloseHandle(process.process);
                CloseHandle(job);
            }
        }
    }
}
