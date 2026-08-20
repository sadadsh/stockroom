import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ICON_BY_ID } from "../lib/iconRegistry";
import {
  AddPartIcon,
  BackIcon,
  BoardIcon,
  BuildIcon,
  CloseIcon,
  CubeArt,
  DoctorIcon,
  DownloadIcon,
  DuplicateIcon,
  EditIcon,
  EnrichIcon,
  ExternalIcon,
  FootprintArt,
  GitIcon,
  InfoIcon,
  LibraryIcon,
  ProjectsIcon,
  RefreshIcon,
  SearchIcon,
  SettingsIcon,
  SymbolArt,
  TrashIcon,
  UploadIcon,
  WarnIcon,
} from "./icons";

function rendered(node: React.ReactElement): SVGSVGElement {
  const { container } = render(node);
  const svg = container.querySelector("svg");
  if (!svg) throw new Error("expected an <svg>");
  return svg;
}

const ALL: Array<{ Comp: (p: { className?: string }) => React.ReactElement | null; id: string }> = [
  { Comp: SearchIcon, id: "action.search" },
  { Comp: WarnIcon, id: "status.warn" },
  { Comp: InfoIcon, id: "status.info" },
  { Comp: UploadIcon, id: "action.upload" },
  { Comp: CloseIcon, id: "action.close" },
  { Comp: BackIcon, id: "nav.back" },
  { Comp: ExternalIcon, id: "action.external" },
  { Comp: LibraryIcon, id: "nav.library" },
  { Comp: AddPartIcon, id: "action.add" },
  { Comp: DuplicateIcon, id: "action.duplicate" },
  { Comp: DoctorIcon, id: "action.doctor" },
  { Comp: SettingsIcon, id: "action.settings" },
  { Comp: DownloadIcon, id: "action.download" },
  { Comp: BuildIcon, id: "action.build" },
  { Comp: RefreshIcon, id: "action.refresh" },
  { Comp: EditIcon, id: "action.edit" },
  { Comp: TrashIcon, id: "action.trash" },
  { Comp: EnrichIcon, id: "action.enrich" },
  { Comp: GitIcon, id: "action.git" },
  { Comp: BoardIcon, id: "nav.cad-assets" },
  { Comp: ProjectsIcon, id: "nav.projects" },
  { Comp: SymbolArt, id: "art.symbol" },
  { Comp: FootprintArt, id: "art.footprint" },
  { Comp: CubeArt, id: "art.model" },
];

describe("icons.tsx wrappers", () => {
  it("keeps all named exports mapped to stable registry ids", () => {
    expect(ALL).toHaveLength(24);
  });

  for (const { Comp, id } of ALL) {
    it(`renders the registered frame for ${id}`, () => {
      const svg = rendered(<Comp />);
      const entry = ICON_BY_ID.get(id);
      expect(entry, id).toBeDefined();
      expect(svg).toHaveAttribute("viewBox", entry?.viewBox);
      expect(svg.children.length).toBeGreaterThan(0);

      if (entry?.family === "tabler-outline") {
        expect(svg).toHaveClass("ico");
        expect(svg).toHaveAttribute("fill", "none");
        expect(svg).toHaveAttribute("stroke", "currentColor");
        expect(svg).toHaveAttribute("stroke-width", "2");
        expect(svg).toHaveAttribute("stroke-linecap", "round");
        expect(svg).toHaveAttribute("stroke-linejoin", "round");
      }

      if (typeof entry?.size === "number") {
        expect(svg).toHaveAttribute("width", String(entry.size));
      } else if (Array.isArray(entry?.size)) {
        expect(svg).toHaveAttribute("width", String(entry.size[0]));
        expect(svg).toHaveAttribute("height", String(entry.size[1]));
      }
    });
  }

  it("forwards caller size classes without changing the shared optical frame", () => {
    const svg = rendered(<LibraryIcon className="h-4 w-4 text-t2" />);
    expect(svg).toHaveClass("ico", "h-4", "w-4", "text-t2");
    expect(svg).toHaveAttribute("stroke-width", "2");
  });
});
