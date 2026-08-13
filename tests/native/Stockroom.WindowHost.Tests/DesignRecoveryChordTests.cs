using System.Windows.Input;

namespace Stockroom.WindowHost.Tests;

public sealed class DesignRecoveryChordTests
{
    [Theory]
    [InlineData(ModifierKeys.Control | ModifierKeys.Shift, true)]
    [InlineData(ModifierKeys.Control, false)]
    [InlineData(ModifierKeys.Shift, false)]
    [InlineData(ModifierKeys.Control | ModifierKeys.Shift | ModifierKeys.Alt, true)]
    public void RequiresControlAndShiftTogether(ModifierKeys modifiers, bool expected)
    {
        Assert.Equal(expected, DesignRecoveryChord.IsPressed(modifiers));
    }
}
