# Source and implementation notes

TuneMeter uses Python's standard library and has no third-party runtime dependencies. It evolved from the project's original UCO collector and material-organizing workflow.

Architectural/format references were inspected; no upstream implementation, prompts or customer data are vendored in this source package. References are not claims of complete upstream compatibility:

- CodeBurn (MIT), provider registry and selected source formats at commit 0322472db34af9f05217b10bea68ee0b17224b67: https://github.com/getagentseal/codeburn
- Pi upstream session identity/fork metadata: https://github.com/badlogic/pi-mono
- Agent Skills format: https://github.com/agentskills/agentskills
- Earlier workflow research: ccusage, spend, memtomem document skills and invoice-ledger-skill; no parsers/services or runtime dependencies were copied.

Provider SPEC declarations document TuneMeter's implementation, not vendor endorsement or exhaustive client schemas. Client names and models identify sources; their trademarks remain with their respective owners.

Synthetic verification scripts construct fictional records. External runtime feedback informed corrections but private logs, report originals and internal delivery rules are not bundled.
