using System.Diagnostics;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using Microsoft.Win32.SafeHandles;

namespace Stockroom.WindowHost;

internal static class WindowsProcessTrust
{
    private const uint ProcessQueryLimitedInformation = 0x1000;
    private const uint TokenQuery = 0x0008;
    private const int TokenUserInformationClass = 1;

    internal static void RequireExpectedParent(uint expectedParentProcessId)
    {
        if (expectedParentProcessId == 0)
        {
            throw new WindowHostException(
                "expected parent process ID is invalid");
        }

        var actualParent = GetParentProcessId();
        if (actualParent != expectedParentProcessId)
        {
            throw new WindowHostException(
                "window-host parent PID did not match the launcher");
        }

        var currentSid = CurrentSid();
        var parentSid = ProcessSid(expectedParentProcessId);
        if (currentSid != parentSid)
        {
            throw new WindowHostException(
                "window-host parent is not owned by the current Windows SID");
        }
    }

    internal static SecurityIdentifier CurrentSid() =>
        WindowsIdentity.GetCurrent().User
        ?? throw new WindowHostException(
            "current Windows SID is unavailable");

    private static uint GetParentProcessId()
    {
        using var process = Process.GetCurrentProcess();
        var information = new ProcessBasicInformation();
        var status = NativeMethods.NtQueryInformationProcess(
            process.SafeHandle,
            0,
            ref information,
            Marshal.SizeOf<ProcessBasicInformation>(),
            out _);
        if (status != 0)
        {
            throw new WindowHostException(
                "window-host parent PID could not be verified");
        }

        var value = information.InheritedFromUniqueProcessId.ToInt64();
        if (value is <= 0 or > uint.MaxValue)
        {
            throw new WindowHostException(
                "window-host parent PID is invalid");
        }

        return checked((uint)value);
    }

    private static SecurityIdentifier ProcessSid(uint processId)
    {
        using var process = NativeMethods.OpenProcess(
            ProcessQueryLimitedInformation,
            false,
            processId);
        if (process.IsInvalid
            || !NativeMethods.OpenProcessToken(
                process,
                TokenQuery,
                out var token))
        {
            throw new WindowHostException(
                "window-host parent SID could not be verified");
        }

        using (token)
        {
            _ = NativeMethods.GetTokenInformation(
                token,
                TokenUserInformationClass,
                IntPtr.Zero,
                0,
                out var required);
            if (required <= 0)
            {
                throw new WindowHostException(
                    "window-host parent SID size is invalid");
            }

            var buffer = Marshal.AllocHGlobal(required);
            try
            {
                if (!NativeMethods.GetTokenInformation(
                        token,
                        TokenUserInformationClass,
                        buffer,
                        required,
                        out _))
                {
                    throw new WindowHostException(
                        "window-host parent SID could not be read");
                }

                var tokenUser = Marshal.PtrToStructure<TokenUser>(buffer);
                return new SecurityIdentifier(tokenUser.User.Sid);
            }
            finally
            {
                Marshal.FreeHGlobal(buffer);
            }
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct ProcessBasicInformation
    {
        internal IntPtr Reserved1;
        internal IntPtr PebBaseAddress;
        internal IntPtr Reserved2_0;
        internal IntPtr Reserved2_1;
        internal IntPtr UniqueProcessId;
        internal IntPtr InheritedFromUniqueProcessId;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct SidAndAttributes
    {
        internal IntPtr Sid;
        internal uint Attributes;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct TokenUser
    {
        internal SidAndAttributes User;
    }
}

internal static class WindowsPipeSecurity
{
    private const int KernelObject = 6;
    private const uint OwnerSecurityInformation = 0x00000001;
    private const uint DaclSecurityInformation = 0x00000004;
    private const int RequiredAccessMask = 0x0012019F;

    internal static void RequireCurrentSidOnly(SafePipeHandle handle)
    {
        ArgumentNullException.ThrowIfNull(handle);
        if (handle.IsInvalid)
        {
            throw new WindowHostException(
                "window-handoff pipe handle is invalid");
        }

        var result = NativeMethods.GetSecurityInfo(
            handle.DangerousGetHandle(),
            KernelObject,
            OwnerSecurityInformation | DaclSecurityInformation,
            out _,
            out _,
            out _,
            out _,
            out var descriptorPointer);
        if (result != 0 || descriptorPointer == IntPtr.Zero)
        {
            throw new WindowHostException(
                "window-handoff pipe security could not be verified");
        }

        try
        {
            var length = NativeMethods.GetSecurityDescriptorLength(
                descriptorPointer);
            if (length is 0 or > 64 * 1024)
            {
                throw new WindowHostException(
                    "window-handoff pipe security descriptor is invalid");
            }

            var bytes = GC.AllocateUninitializedArray<byte>(
                checked((int)length));
            Marshal.Copy(
                descriptorPointer,
                bytes,
                0,
                bytes.Length);
            var descriptor = new RawSecurityDescriptor(bytes, 0);
            var currentSid = WindowsProcessTrust.CurrentSid();
            if (descriptor.Owner != currentSid
                || !descriptor.ControlFlags.HasFlag(
                    ControlFlags.DiscretionaryAclPresent)
                || !descriptor.ControlFlags.HasFlag(
                    ControlFlags.DiscretionaryAclProtected)
                || descriptor.DiscretionaryAcl is null
                || descriptor.DiscretionaryAcl.Count != 1
                || descriptor.DiscretionaryAcl[0] is not CommonAce ace
                || ace.AceQualifier != AceQualifier.AccessAllowed
                || ace.SecurityIdentifier != currentSid
                || ace.AccessMask != RequiredAccessMask
                || ace.AceFlags != AceFlags.None)
            {
                throw new WindowHostException(
                    "window-handoff pipe is not current-SID-only");
            }
        }
        finally
        {
            _ = NativeMethods.LocalFree(descriptorPointer);
        }
    }
}

internal sealed class SecureNamedPipeConnection
{
    private const int ConnectTimeoutMilliseconds = 15_000;

    internal static NamedPipeClientStream Connect(
        string pipeName,
        uint expectedServerProcessId)
    {
        WindowsProcessTrust.RequireExpectedParent(
            expectedServerProcessId);
        var stream = new NamedPipeClientStream(
            ".",
            pipeName,
            PipeDirection.InOut,
            PipeOptions.Asynchronous,
            TokenImpersonationLevel.Identification);
        try
        {
            stream.Connect(ConnectTimeoutMilliseconds);
            stream.ReadMode = PipeTransmissionMode.Byte;
            if (!NativeMethods.GetNamedPipeServerProcessId(
                    stream.SafePipeHandle,
                    out var actualServerProcessId)
                || actualServerProcessId != expectedServerProcessId)
            {
                throw new WindowHostException(
                    "window-handoff server PID did not match the expected parent");
            }

            WindowsPipeSecurity.RequireCurrentSidOnly(
                stream.SafePipeHandle);
            return stream;
        }
        catch
        {
            stream.Dispose();
            throw;
        }
    }
}

internal static partial class NativeMethods
{
    [LibraryImport("ntdll.dll")]
    internal static partial int NtQueryInformationProcess(
        SafeProcessHandle processHandle,
        int processInformationClass,
        ref WindowsProcessTrust.ProcessBasicInformation processInformation,
        int processInformationLength,
        out int returnLength);

    [LibraryImport("kernel32.dll", SetLastError = true)]
    internal static partial SafeProcessHandle OpenProcess(
        uint desiredAccess,
        [MarshalAs(UnmanagedType.Bool)] bool inheritHandle,
        uint processId);

    [LibraryImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static partial bool OpenProcessToken(
        SafeProcessHandle processHandle,
        uint desiredAccess,
        out SafeAccessTokenHandle tokenHandle);

    [LibraryImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static partial bool GetTokenInformation(
        SafeAccessTokenHandle tokenHandle,
        int tokenInformationClass,
        IntPtr tokenInformation,
        int tokenInformationLength,
        out int returnLength);

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static partial bool GetNamedPipeServerProcessId(
        SafePipeHandle pipe,
        out uint serverProcessId);

    [LibraryImport("advapi32.dll")]
    internal static partial uint GetSecurityInfo(
        IntPtr handle,
        int objectType,
        uint securityInfo,
        out IntPtr owner,
        out IntPtr group,
        out IntPtr dacl,
        out IntPtr sacl,
        out IntPtr securityDescriptor);

    [LibraryImport("advapi32.dll")]
    internal static partial uint GetSecurityDescriptorLength(
        IntPtr securityDescriptor);

    [LibraryImport("kernel32.dll")]
    internal static partial IntPtr LocalFree(IntPtr memory);
}
