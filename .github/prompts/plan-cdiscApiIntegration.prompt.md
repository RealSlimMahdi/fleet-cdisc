## Plan: CDISC API Integration & Codelist Generation

This plan implements a client for the CDISC Library API to download Controlled Terminology (CT) and a generator script to create Python constants for IDE auto-completion. This ensures AI agents and developers have explicit, statically typed access to CDISC codelists (e.g., `Codelist.SEX = "C66731"`) while natively supporting both custom mapping and perfect-match raw data.

**Steps**

1. **API Client Phase**
   - Create `CDISCClient` wrapping `httpx` to handle authentication and base URLs.
   - Implement `get_packages` to list available CT versions.
   - Implement `get_codelist` to download specific `conceptId` JSON data (containing `submissionValue` and `terms`).
2. **Code Generation Phase** (_depends on Step 1_)
   - Create `CodelistGenerator` that parses the CDISC JSON response.
   - Map `conceptId` to class names (e.g., `class C66731: M = "M"`).
   - Output a cleanly formatted Python module containing these classes.
3. **Integration & Refinement Phase** (_parallel with Step 2, depends on Step 1_)
   - Update `StudyContext` schema to support optionally configuring the path to the generated CT module.
   - Refine `assign_ct` docstrings to clarify that `ct_mapping` is optional: if raw data perfectly matches the standard (e.g., source is already `"M"`), it acts as a passthrough strictly validated against the `ct_codelist`.

**Relevant files**

- [src/fleet/ct/api.py](src/fleet/ct/api.py) — Create `CDISCClient` class using `httpx` and `pydantic-settings` to load `.env` configurations.
- [src/fleet/ct/generator.py](src/fleet/ct/generator.py) — Create `generate_codelist_module()` to convert CDISC JSON responses into a Python AST or string template.
- [src/fleet/sdtm/namespace.py](src/fleet/sdtm/namespace.py#L122) — Update `assign_ct` docstring to explicitly describe the behavior when `ct_mapping` is omitted.
- [specs/cdiscpilot01/sdtm/codelists.py](specs/cdiscpilot01/sdtm/codelists.py) — Target location for the dev-generated file (should be ignored in Git outside of dev examples).

**Verification**

1. Run `pytest` and verify existing `test_ct_validation.py` passes without modification.
2. Manually test `CDISCClient.get_codelist("C66731")` with a valid API key in a `.env` file to ensure the response correctly returns the "M" and "F" terms.
3. Run the generator script and verify `codelists.py` is created with valid Python syntax.
4. Open the generated `codelists.py` in VS Code, import `C66731` in a script, and verify IDE auto-completion suggests `.M` and `.F`.

**Decisions**

- Configuration: `CDISC_BASE_URL` (defaulting to CDISC Library API) and `CDISC_API_KEY` will initially be loaded via a `.env` file, paving the way for full environment variable support.
- File Output: Generated Python modules are local, unversioned artifacts generated on-the-fly via user scripts, mapped via the configuration file, but we will store one in `specs/cdiscpilot01/sdtm/` solely for pipeline development testing.
- `ct_mapping` vs `ct_codelist`: They are complementary. If the raw data perfectly matches the standard (e.g., "M" -> "M"), `ct_mapping` can be safely omitted while `ct_codelist` strictly targets NCI validation.

**Further Considerations**

1. Do you want the generator to also pull in the `definition` and `preferredTerm` from the CDISC JSON to inject into the Python docstrings of the generated classes? (Option A: Yes, for richer AI context / Option B: No, keep the file lightweight).
2. For enterprise firewalls, do we need to expose SSL verification bypassing parameters in the `CDISCClient`?
