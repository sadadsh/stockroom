using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Stockroom.WindowHost;

internal sealed class SensitiveCredential : IDisposable
{
    private static readonly Regex CanonicalPattern = new(
        @"\A[A-Za-z0-9_-]{43}\z",
        RegexOptions.CultureInvariant | RegexOptions.NonBacktracking);

    private byte[] _ascii;
    private bool _disposed;

    private SensitiveCredential(byte[] ascii)
    {
        _ascii = ascii;
    }

    internal static SensitiveCredential Parse(JsonElement element, string label)
    {
        if (element.ValueKind != JsonValueKind.String)
        {
            throw new WindowHostException(
                $"{label} must be a 256-bit base64url credential");
        }

        var value = element.GetString();
        if (value is null || !CanonicalPattern.IsMatch(value))
        {
            throw new WindowHostException(
                $"{label} must be a 256-bit base64url credential");
        }

        byte[] decoded;
        try
        {
            decoded = Convert.FromBase64String(
                value.Replace('-', '+').Replace('_', '/') + "=");
        }
        catch (FormatException exception)
        {
            throw new WindowHostException(
                $"{label} must be a 256-bit base64url credential",
                exception);
        }

        try
        {
            var canonical = Convert.ToBase64String(decoded)
                .TrimEnd('=')
                .Replace('+', '-')
                .Replace('/', '_');
            var canonicalBytes = Encoding.ASCII.GetBytes(canonical);
            var valueBytes = Encoding.ASCII.GetBytes(value);
            try
            {
                if (decoded.Length != 32
                    || canonicalBytes.Length != valueBytes.Length
                    || !CryptographicOperations.FixedTimeEquals(
                        canonicalBytes,
                        valueBytes))
                {
                    throw new WindowHostException(
                        $"{label} must be a 256-bit base64url credential");
                }

                return new SensitiveCredential(valueBytes);
            }
            finally
            {
                CryptographicOperations.ZeroMemory(canonicalBytes);
            }
        }
        finally
        {
            CryptographicOperations.ZeroMemory(decoded);
        }
    }

    internal ReadOnlySpan<byte> Bytes
    {
        get
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            return _ascii;
        }
    }

    internal string CreateEphemeralString()
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        return Encoding.ASCII.GetString(_ascii);
    }

    internal bool FixedTimeEquals(SensitiveCredential other)
    {
        ArgumentNullException.ThrowIfNull(other);
        ObjectDisposedException.ThrowIf(_disposed, this);
        return _ascii.Length == other.Bytes.Length
            && CryptographicOperations.FixedTimeEquals(_ascii, other.Bytes);
    }

    internal bool OccursIn(ReadOnlySpan<byte> candidate)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        return candidate.IndexOf(_ascii) >= 0;
    }

    internal string HmacHex(ReadOnlySpan<byte> message)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        var digest = HMACSHA256.HashData(_ascii, message);
        try
        {
            return Convert.ToHexStringLower(digest);
        }
        finally
        {
            CryptographicOperations.ZeroMemory(digest);
        }
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        CryptographicOperations.ZeroMemory(_ascii);
        _ascii = [];
        _disposed = true;
    }
}
