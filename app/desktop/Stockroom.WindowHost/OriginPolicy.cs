namespace Stockroom.WindowHost;

internal static class OriginPolicy
{
    internal static bool IsAllowedNavigation(
        string? candidate,
        Uri expectedOrigin,
        bool allowInitialBlank = false)
    {
        if (allowInitialBlank
            && string.Equals(
                candidate,
                "about:blank",
                StringComparison.Ordinal))
        {
            return true;
        }

        return TrySameOrigin(candidate, expectedOrigin, out _);
    }

    internal static bool IsApiRequest(
        string? candidate,
        Uri expectedOrigin)
    {
        if (!TrySameOrigin(
                candidate,
                expectedOrigin,
                out var parsed))
        {
            return false;
        }

        return parsed.AbsolutePath == "/api"
            || parsed.AbsolutePath.StartsWith(
                "/api/",
                StringComparison.Ordinal);
    }

    internal static bool TryExternalNavigation(
        string? candidate,
        out Uri parsed)
    {
        parsed = null!;
        if (string.IsNullOrEmpty(candidate)
            || !Uri.TryCreate(candidate, UriKind.Absolute, out var candidateUri)
            || !string.IsNullOrEmpty(candidateUri.UserInfo)
            || (candidateUri.Scheme != Uri.UriSchemeHttps
                && candidateUri.Scheme != "ms-windows-store"))
        {
            return false;
        }

        parsed = candidateUri;
        return true;
    }

    private static bool TrySameOrigin(
        string? candidate,
        Uri expectedOrigin,
        out Uri parsed)
    {
        parsed = null!;
        if (string.IsNullOrEmpty(candidate)
            || !Uri.TryCreate(candidate, UriKind.Absolute, out var candidateUri)
            || candidateUri.Scheme != Uri.UriSchemeHttp
            || candidateUri.Host != "127.0.0.1"
            || candidateUri.Port != expectedOrigin.Port
            || !string.IsNullOrEmpty(candidateUri.UserInfo))
        {
            return false;
        }

        parsed = candidateUri;
        return true;
    }
}
