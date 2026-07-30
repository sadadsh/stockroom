"""Versioned shared component-template contracts."""

from .passive import (
    PassiveTemplateArtifact,
    PassiveTemplateDefinition,
    PassiveTemplateTerminal,
    PassiveToolTemplateBinding,
    TemplateTerminalBinding,
    passive_template_definition,
    representative_passive_template,
    template_contract_digest,
)

__all__ = [
    "PassiveTemplateArtifact",
    "PassiveTemplateDefinition",
    "PassiveTemplateTerminal",
    "PassiveToolTemplateBinding",
    "TemplateTerminalBinding",
    "passive_template_definition",
    "representative_passive_template",
    "template_contract_digest",
]
