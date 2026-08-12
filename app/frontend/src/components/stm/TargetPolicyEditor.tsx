/**
 * TargetPolicyEditor: the caller-owned target-definition rules, as editable JSON. The default
 * policy itself lives in ./coreBringUpPolicy so this file exports only its component.
 */
import { useRef, useState } from "react";
import type { TargetDefinitionPolicy } from "../../api/types";
import { Text, useText } from "../../lib/copy";
import { Button, Eyebrow } from "../primitives";
import { cloneCoreBringUpPolicy } from "./coreBringUpPolicy";

// The editable text, plus the policy it was seeded from and any parse complaint against it.
interface Edit {
  from: TargetDefinitionPolicy;
  text: string;
  error: string;
}

function seed(policy: TargetDefinitionPolicy): Edit {
  return { from: policy, text: JSON.stringify(policy, null, 2), error: "" };
}

export function TargetPolicyEditor({
  policy,
  onPolicyChange,
}: {
  policy: TargetDefinitionPolicy;
  onPolicyChange: (policy: TargetDefinitionPolicy) => void;
}) {
  // The draft is held WITH the policy it was seeded from and read back only for that policy, so a
  // new policy shows its own JSON on the very render it arrives. Re-seeding through an effect
  // instead cost a render where the previous policy's text (and its error) were still on screen.
  const [edit, setEdit] = useState<Edit>(() => seed(policy));
  const current = edit.from === policy ? edit : seed(policy);
  const draft = current.text;
  const error = current.error;
  const fileInput = useRef<HTMLInputElement>(null);
  const draftLabel = useText(
    "stm.target.policy.draft.aria",
    "Target Definition Rules JSON",
  );

  const apply = () => {
    try {
      const parsed = JSON.parse(draft) as TargetDefinitionPolicy;
      if (!parsed || typeof parsed !== "object" || !parsed.id) {
        throw new Error("Policy needs a non-empty id.");
      }
      if (!Array.isArray(parsed.requirements) || !Array.isArray(parsed.safety_rules)) {
        throw new Error("Policy needs requirements and safety_rules arrays.");
      }
      // The accepted policy comes straight back as the new prop, which re-seeds the draft from it.
      onPolicyChange(parsed);
      setEdit({ from: parsed, text: JSON.stringify(parsed, null, 2), error: "" });
    } catch (caught) {
      setEdit({
        from: policy,
        text: draft,
        error: caught instanceof Error ? caught.message : "Policy JSON is invalid.",
      });
    }
  };

  const loadFile = async (file: File | undefined) => {
    if (!file) return;
    const text = await file.text();
    setEdit({ from: policy, text, error: "" });
  };

  return (
    <details data-dev-id="stm.target-policy" className="rounded-card border border-line bg-surface">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3">
        <span>
          <Eyebrow>
            <Text id="stm.target.policy.title">Definition Rules</Text>
          </Eyebrow>
          <span className="mt-0.5 block font-mono text-xs text-t1">{policy.id}</span>
        </span>
        <span className="text-2xs text-t3">
          <Text id="stm.target.policy.edit-json">Edit JSON</Text>
        </span>
      </summary>
      <div className="border-t border-line px-4 pb-4 pt-3">
        <p className="mb-3 text-xs text-t3">
          <Text id="stm.target.policy.explanation">Each run inventories the functional power, ground, regulator, reset, boot, clock, and reserved-pin foundation. These rules add access services, required routes, target scope, safe-state handling, and implementation-neutral routing requirements. Stockroom specifies connection behavior and safe states, while the consuming design chooses the switching, selection, or isolation method. Pin capabilities remain distinct from rescue or data-access support evidenced from outside, and the whole ruleset is included in the artifact digest.</Text>
        </p>
        <textarea
          value={draft}
          onChange={(event) => setEdit({ from: policy, text: event.target.value, error: "" })}
          aria-label={draftLabel}
          spellCheck={false}
          className="h-64 w-full resize-y rounded-control bg-field p-3 font-mono text-xs text-t1 outline-none focus:ring-1 focus:ring-acc"
        />
        {error ? <p className="mt-2 text-xs text-err-text">{error}</p> : null}
        <div className="mt-3 flex flex-wrap gap-2">
          <Button small onClick={apply}>
            <Text id="stm.target.policy.apply">Commit Rules</Text>
          </Button>
          <Button small onClick={() => fileInput.current?.click()}>
            <Text id="stm.target.policy.load-json">Load JSON</Text>
          </Button>
          <Button
            small
            onClick={() => {
              const reset = cloneCoreBringUpPolicy();
              setEdit(seed(reset));
              onPolicyChange(reset);
            }}
          >
            <Text id="stm.target.policy.reset">Reset Access Profile</Text>
          </Button>
          <input
            ref={fileInput}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={(event) => void loadFile(event.target.files?.[0])}
          />
        </div>
      </div>
    </details>
  );
}
