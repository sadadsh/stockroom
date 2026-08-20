/**
 * The compact IconButton is the app's ONE destructive/pending interaction language (punch 15: a red
 * X that expands to "Delete Part?" on hover, with a loading state - which the owner generalised to
 * "this interactive/loading philosophy should be used across the app").
 *
 * It shipped with the reveal-on-hover/focus behaviour already right, and with ZERO tests and ZERO
 * callers - so the app hand-rolled one-off buttons while the proper primitive sat unused. These
 * tests lock the behaviour before anything adopts it.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { IconButton } from "./primitives";
import { TrashIcon } from "./icons";

describe("IconButton compact", () => {
  it("names its action to a screen reader while collapsed to a glyph", () => {
    // Collapsed it shows no text at all, so the accessible name is the ONLY thing a
    // non-sighted user has. It comes from aria-label, with title for the pointer tooltip.
    render(<IconButton compact icon={<TrashIcon />} label="Delete Part?" />);
    const button = screen.getByRole("button", { name: "Delete Part?" });
    expect(button).toHaveAttribute("title", "Delete Part?");
  });

  it("holds a FIXED width, so a toolbar does not reflow under the pointer", () => {
    // The label used to wipe open on hover, animating a one-column grid 0fr -> 1fr so the button
    // grew to the label's own width. Lovely on a page, wrong in a toolbar: a control that changes
    // width when the pointer crosses it moves the next control before you reach it. The label now
    // lives where a Windows toolbar puts it - in aria-label and title - which costs no layout.
    render(<IconButton compact icon={<TrashIcon />} label="Delete Part?" />);
    const button = screen.getByRole("button", { name: "Delete Part?" });
    expect(button.textContent?.trim()).toBe("");
    expect(button.className).toMatch(/w-\[\d+px\]/);
    expect(button.className).not.toContain("grid-cols-");
  });

  it("honours its tone in compact mode, so a destructive action can read as destructive", () => {
    // Compact mode used to hardcode the neutral treatment and IGNORE variant, so a delete could not
    // be red at all - which is exactly what punch 15 asked for. At REST the tone is a muted tint
    // rather than the full ghost-danger treatment (see the quiet-at-rest cases below), so this
    // asserts the err token is in play without asserting the loud form.
    render(
      <IconButton compact variant="ghost-danger" icon={<TrashIcon />} label="Delete Part?" />,
    );
    expect(screen.getByRole("button").className).toContain("--c-err");
  });

  it("states what is happening while pending, using the verb the toast will use", () => {
    render(
      <IconButton
        compact
        icon={<TrashIcon />}
        label="Delete Part?"
        pending
        pendingLabel="Deleting"
      />,
    );
    const button = screen.getByRole("button", { name: "Deleting" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
  });

  it("refuses a second click while pending", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <IconButton
        compact
        icon={<TrashIcon />}
        label="Delete Part?"
        pending
        pendingLabel="Deleting"
        onClick={onClick}
      />,
    );
    await user.click(screen.getByRole("button"));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("stays toned while pending, so the control cannot go quiet mid-action", () => {
    render(
      <IconButton
        compact
        icon={<TrashIcon />}
        label="Delete Part?"
        pending
        pendingLabel="Deleting"
      />,
    );
    // Pinned on by `pending` rather than by hover state, which a running action cannot rely on:
    // the pointer may well have left. The variant tone arrives whole, so a running destructive
    // action still reads as destructive.
    const button = screen.getByRole("button");
    expect(button.getAttribute("data-revealed")).toBe("true");
    expect(button.className).not.toContain("border-transparent");
  });

  it("runs its action on click when idle", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <IconButton compact icon={<TrashIcon />} label="Delete Part?" onClick={onClick} />,
    );
    await user.click(screen.getByRole("button", { name: "Delete Part?" }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("falls back to the ordinary icon+label Button when not compact", () => {
    render(<IconButton icon={<TrashIcon />} label="Delete Part" />);
    // the full button shows its label as visible text, no reveal needed
    expect(screen.getByRole("button", { name: /Delete Part/ })).toBeTruthy();
  });
});

describe("IconButton compact is quiet at rest", () => {
  it("wears no border or tint until approached, so a destructive glyph does not shout", () => {
    // Caught in a screenshot: applying the tone at ALL times turned Delete Part into a permanently
    // bordered red box in the corner - LOUDER than the dim text it replaced, and against the
    // repo's own rule that a ghost-danger trigger "reads as available without shouting". The tone
    // belongs to the revealed state, arriving with the label.
    render(
      <IconButton compact variant="ghost-danger" icon={<TrashIcon />} label="Delete Part?" />,
    );
    const button = screen.getByRole("button");
    expect(button.getAttribute("data-revealed")).toBe("false");
    expect(button.className).toContain("border-transparent");
    expect(button.className).not.toContain("text-err-text");
  });

  it("takes on its tone the moment it is focused", async () => {
    const user = userEvent.setup();
    render(
      <IconButton compact variant="ghost-danger" icon={<TrashIcon />} label="Delete Part?" />,
    );
    await user.tab();
    const button = screen.getByRole("button");
    expect(button.getAttribute("data-revealed")).toBe("true");
    expect(button.className).toContain("text-err-text");
  });

  it("is already wearing its tone while pending, without needing a pointer", () => {
    render(
      <IconButton
        compact
        variant="ghost-danger"
        icon={<TrashIcon />}
        label="Delete Part?"
        pending
        pendingLabel="Deleting"
      />,
    );
    const button = screen.getByRole("button");
    expect(button.getAttribute("data-revealed")).toBe("true");
    expect(button.className).toContain("text-err-text");
  });
});
