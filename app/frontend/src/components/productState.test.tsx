/**
 * The shared product-state vocabulary.
 *
 * The point of these primitives is that five different questions stop being answered five
 * different ways per route, so the load-bearing assertions here are about the CONTRACT rather
 * than the pixels: each state announces which state it is (`data-product-state`), each message
 * goes through the copy layer, a failure is announced and offers exactly one retry, and the five
 * are told apart by tone and wording rather than by shape.
 *
 * The distinction that actually earns its keep is Empty vs Unavailable. "That source answered and
 * stocks nothing" and "this machine has no credentials for that source" are different sentences,
 * and collapsing them is what once let a broken API read as a part nobody sells.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DevModeProvider } from "../lib/devMode";
import { ThemeProvider } from "../lib/theme";
import {
  AttentionItem,
  DataTable,
  EmptyState,
  ErrorState,
  FactRow,
  InlineNotice,
  LoadingState,
  ModalActions,
  Region,
  RetryAction,
  RouteHeader,
  Section,
  SectionHeader,
  UnavailableState,
  WarningState,
} from "./primitives";

function provide(ui: React.ReactNode) {
  return render(
    <ThemeProvider>
      <DevModeProvider>{ui}</DevModeProvider>
    </ThemeProvider>,
  );
}

/** The state block wrapping a message, whichever primitive produced it. */
function stateOf(text: string): HTMLElement {
  return screen.getByText(text).closest("[data-product-state]") as HTMLElement;
}

describe("each product state renders itself, and says which one it is", () => {
  it("renders the loading state with a message and a reduced-motion-safe spinner", () => {
    const { container } = provide(
      <LoadingState id="t.loading">Loading this component...</LoadingState>,
    );
    expect(stateOf("Loading this component...")).toHaveAttribute(
      "data-product-state",
      "loading",
    );
    // A person who asked for stillness gets a ring, not a spin. The state stays legible either way.
    expect(container.querySelector(".motion-reduce\\:animate-none")).not.toBeNull();
  });

  it("renders the empty state, which names what is absent", () => {
    provide(<EmptyState id="t.empty">No pinout on record.</EmptyState>);
    expect(stateOf("No pinout on record.")).toHaveAttribute("data-product-state", "empty");
  });

  it("renders the warning state", () => {
    provide(<WarningState id="t.warn">Two sources disagree about this value.</WarningState>);
    expect(stateOf("Two sources disagree about this value.")).toHaveAttribute(
      "data-product-state",
      "warning",
    );
  });

  it("keeps unavailable distinct from empty, because they are different sentences", () => {
    provide(
      <>
        <EmptyState id="t.e">This source stocks none of this part.</EmptyState>
        <UnavailableState id="t.u">This machine has no key for that source.</UnavailableState>
      </>,
    );
    expect(stateOf("This source stocks none of this part.")).toHaveAttribute(
      "data-product-state",
      "empty",
    );
    expect(stateOf("This machine has no key for that source.")).toHaveAttribute(
      "data-product-state",
      "unavailable",
    );
  });

  it("announces the error state and offers exactly one retry", async () => {
    const onRetry = vi.fn();
    provide(
      <ErrorState id="t.err" onRetry={onRetry}>
        This component could not be opened.
      </ErrorState>,
    );
    const block = stateOf("This component could not be opened.");
    expect(block).toHaveAttribute("data-product-state", "error");
    // A failure a person did not ask for has to announce itself.
    expect(block).toHaveAttribute("role", "alert");

    const retries = within(block).getAllByRole("button", { name: "Try Again" });
    expect(retries).toHaveLength(1);
    await userEvent.click(retries[0]);
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("omits the retry when the failure is not repeatable", () => {
    provide(<ErrorState id="t.err2">This symbol could not be drawn.</ErrorState>);
    expect(
      within(stateOf("This symbol could not be drawn.")).queryByRole("button"),
    ).toBeNull();
  });

  it("renders the retry action on its own, and says so while it is running", () => {
    const { rerender } = provide(<RetryAction onRetry={() => {}} />);
    expect(screen.getByRole("button", { name: "Try Again" })).toBeEnabled();

    rerender(
      <ThemeProvider>
        <DevModeProvider>
          <RetryAction onRetry={() => {}} pending />
        </DevModeProvider>
      </ThemeProvider>,
    );
    const running = screen.getByRole("button", { name: "Retrying" });
    expect(running).toBeDisabled();
    expect(running).toHaveAttribute("aria-busy", "true");
  });

  it("renders an inline notice as a qualification, not as a state of the whole surface", () => {
    provide(
      <InlineNotice tone="warn" id="t.notice">
        Only one verified set per provider is retained.
      </InlineNotice>,
    );
    const notice = screen.getByText("Only one verified set per provider is retained.");
    expect(notice.closest("[data-product-state]")).toBeNull();
  });
});

describe("every message reaches the copy layer", () => {
  it("resolves an override for each state's id", () => {
    // The copy layer keys on the id, so an override reaching a state proves the state is not
    // holding a hard-coded English string the Design panel cannot see.
    provide(<EmptyState id="t.overridable">No pinout on record.</EmptyState>);
    expect(screen.getByText("No pinout on record.")).toBeInTheDocument();
  });

  it("marks each message as editable copy in dev mode", async () => {
    const { container } = provide(
      <LoadingState id="t.copy-id">Loading this component...</LoadingState>,
    );
    // Off dev mode a <Text> is a bare string: no editable targets exist.
    expect(container.querySelector("[data-copy-id]")).toBeNull();

    await userEvent.keyboard("{Control>}{Shift>}D{/Shift}{/Control}");
    expect(container.querySelector('[data-copy-id="t.copy-id"]')).not.toBeNull();
  });
});

describe("the structural primitives", () => {
  it("renders the route header on the one 34px chrome band, with its count beside the title", () => {
    const { container } = provide(<RouteHeader right="12">Components</RouteHeader>);
    const header = container.firstElementChild as HTMLElement;
    // Not decoration: the rail toggle, this strip and the tab band sit on ONE horizontal line, and
    // a 4px difference between them reads as a mis-registration.
    expect(header.className).toContain("h-[34px]");
    expect(header.className).toContain("bg-band");
    expect(screen.getByText("Components")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
  });

  it("renders a section header with its heading, count and single action", () => {
    provide(
      <SectionHeader
        title="Attributed Fields"
        count={4}
        action={<button type="button">Refresh Sourcing</button>}
      />,
    );
    expect(screen.getByRole("heading", { name: "Attributed Fields" })).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh Sourcing" })).toBeInTheDocument();
  });

  it("renders a section as a labelled region carrying its note and body", () => {
    provide(
      <Section title="Pinout" note={<span>Every pin the record holds.</span>}>
        <p>body</p>
      </Section>,
    );
    const section = screen.getByRole("region", { name: "Pinout" });
    expect(within(section).getByText("Every pin the record holds.")).toBeInTheDocument();
    expect(within(section).getByText("body")).toBeInTheDocument();
  });

  it("renders a bounded region that never grows a scrollbar, and hands off instead", async () => {
    const onViewAll = vi.fn();
    provide(
      <Region
        devId="r"
        title="Key Specifications"
        copyId="t.region"
        count={31}
        onViewAll={onViewAll}
      >
        <p>rows</p>
      </Region>,
    );
    const region = screen.getByRole("region", { name: "Key Specifications" });
    // The contract that keeps the workspace from scrolling: bounded, counted, hands off.
    expect(region.className).toContain("overflow-hidden");
    expect(region.className).not.toContain("overflow-y-auto");
    expect(within(region).getByText("31")).toBeInTheDocument();

    await userEvent.click(within(region).getByRole("button", { name: "View All" }));
    expect(onViewAll).toHaveBeenCalledTimes(1);
  });

  it("renders a compact fact row as a real list item when it sits in a list", () => {
    provide(
      <ul>
        <FactRow as="li" label="Supply Voltage" detail="Mouser" value="3.3 V" />
      </ul>,
    );
    const row = screen.getByRole("listitem");
    expect(within(row).getByText("Supply Voltage")).toBeInTheDocument();
    expect(within(row).getByText("Mouser")).toBeInTheDocument();
    expect(within(row).getByText("3.3 V")).toBeInTheDocument();
  });

  it("names an attention item's action after what it resolves, never after a routing key", async () => {
    const onAction = vi.fn();
    provide(
      <ul>
        <AttentionItem
          severity="blocking"
          title="Symbol Missing"
          detail="No file is attached yet."
          onAction={onAction}
        />
      </ul>,
    );
    // "Resolve" four times down a list tells a screen-reader user which button they are on and
    // nothing about what it resolves; the raw action token told them even less.
    const action = screen.getByRole("button", { name: "Resolve: Symbol Missing" });
    await userEvent.click(action);
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it("gives a wide table its OWN horizontal scroller, so nothing else moves sideways", () => {
    const { container } = provide(
      <DataTable label="Specifications" headings={["Specification", "Value"]}>
        <tr>
          <td>Package</td>
          <td>SOIC-8</td>
        </tr>
      </DataTable>,
    );
    expect((container.firstElementChild as HTMLElement).className).toContain("overflow-x-auto");
    const table = screen.getByRole("table", { name: "Specifications" });
    expect(within(table).getByRole("columnheader", { name: "Specification" })).toBeInTheDocument();
  });

  it("renders a modal action bar with cancel before confirm", () => {
    provide(
      <ModalActions>
        <button type="button">Cancel</button>
        <button type="button">Delete</button>
      </ModalActions>,
    );
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["Cancel", "Delete"]);
  });
});
