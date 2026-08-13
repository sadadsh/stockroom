using System.Windows.Input;

namespace Stockroom.WindowHost;

internal static class DesignRecoveryChord
{
    internal static bool IsPressed(ModifierKeys modifiers) =>
        modifiers.HasFlag(ModifierKeys.Control)
        && modifiers.HasFlag(ModifierKeys.Shift);
}
