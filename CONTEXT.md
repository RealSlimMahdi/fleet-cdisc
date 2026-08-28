# Fleet

CDISC-compliant clinical data derivation, expressed as Polars namespace extensions. Raw study data goes in; SDTM domains, ADaM datasets, and the Define-XML that describes them come out.

## Language

### Tooling surface

**Introspection surface**:
The narrow, additive-only set of names Fleet publishes for tooling that needs to _describe_ Fleet rather than run a derivation — algorithm catalogues, parameter tables, the define schema. Distinct from the derivation API, which is aimed at analysts.
_Avoid_: public API, tooling API

**Protocol adapter**:
A module that translates an external wire protocol into calls on Fleet's own registries and holds no clinical knowledge of its own. The language server and the MCP server are the two that exist.
_Avoid_: server, integration, backend
