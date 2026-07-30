namespace Stockroom.WindowHost;

internal sealed class WindowHostException : Exception
{
    internal WindowHostException(string message)
        : base(message)
    {
    }

    internal WindowHostException(string message, Exception innerException)
        : base(message, innerException)
    {
    }
}
