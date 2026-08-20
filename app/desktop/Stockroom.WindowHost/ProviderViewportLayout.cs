namespace Stockroom.WindowHost;

internal sealed record ProviderViewportRequest(
    string ComponentId,
    string ProviderId,
    string RouteId,
    string SessionId,
    bool Visible,
    double X,
    double Y,
    double Width,
    double Height)
{
    internal ProviderBrowserSurfaceIdentity Identity => new(
        ComponentId,
        ProviderId,
        RouteId,
        SessionId);
}

internal sealed record ProviderViewportLayout(
    double X,
    double Y,
    double Width,
    double Height)
{
    private const double MinimumWidth = 320;
    private const double MinimumHeight = 240;

    internal static bool TryResolve(
        ProviderViewportRequest request,
        string expectedComponentId,
        double availableWidth,
        double availableHeight,
        out ProviderViewportLayout? layout)
    {
        ArgumentNullException.ThrowIfNull(request);
        layout = null;
        if (!request.Visible
            || !request.Identity.IsValid
            || !string.Equals(
                request.ComponentId,
                expectedComponentId,
                StringComparison.Ordinal)
            || !double.IsFinite(request.X)
            || !double.IsFinite(request.Y)
            || !double.IsFinite(request.Width)
            || !double.IsFinite(request.Height)
            || !double.IsFinite(availableWidth)
            || !double.IsFinite(availableHeight)
            || request.X < 0
            || request.Y < 0
            || request.Width < MinimumWidth
            || request.Height < MinimumHeight
            || request.X + request.Width > availableWidth
            || request.Y + request.Height > availableHeight)
        {
            return false;
        }

        layout = new ProviderViewportLayout(
            request.X,
            request.Y,
            request.Width,
            request.Height);
        return true;
    }
}
