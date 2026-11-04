"""ODM OIDs shared by the Define-XML and Dataset-JSON writers.

A Dataset-JSON ``itemOID`` must be the ``ItemDef/@OID`` of the Define-XML
that describes the file (Dataset-JSON 1.1), so both writers build their
OIDs here.
"""

from __future__ import annotations

#: Variables that share one ItemDef across datasets, so their OID has no dataset part.
SHARED_ITEMS = frozenset(
    {
        "STUDYID",
        "USUBJID",
        "DOMAIN",
        "SUBJID",
        "SITEID",
        "AGE",
        "AGEU",
        "SEX",
        "RACE",
        "ETHNIC",
        "ARMCD",
        "ARM",
        "ACTARMCD",
        "ACTARM",
    }
)


def item_oid(dataset: str, variable: str) -> str:
    """Return the ItemDef OID of *variable* in *dataset*.

    Args:
        dataset: Dataset name, for example ``"DM"``.
        variable: Variable name, for example ``"AGE"``.

    Returns:
        str: ``IT.<variable>`` for a shared variable, else ``IT.<dataset>.<variable>``.

    Examples:
        The same OID in the Define-XML and in Dataset-JSON::

            from fleet.core.oids import item_oid

            assert item_oid("DM", "STUDYID") == "IT.STUDYID"
            assert item_oid("DM", "BRTHDTC") == "IT.DM.BRTHDTC"
    """
    if variable in SHARED_ITEMS:
        return f"IT.{variable}"
    return f"IT.{dataset}.{variable}"


def study_oid(study_id: str) -> str:
    """Return the Study OID for *study_id* (``STDY.<id>``).

    Args:
        study_id: The ``study.id`` of the define.yaml.

    Returns:
        str: The OID.

    Examples:
        Build the OID::

            from fleet.core.oids import study_oid

            assert study_oid("CDISCPILOT01") == "STDY.CDISCPILOT01"
    """
    return f"STDY.{study_id}"


def metadata_version_oid(study_id: str, standard: str, version: str) -> str:
    """Return the MetaDataVersion OID of a study define.

    Args:
        study_id: The ``study.id`` of the define.yaml.
        standard: The ``study.standard``, for example ``"SDTMIG"``.
        version: The ``study.standard_version``, for example ``"3.4"``.

    Returns:
        str: ``MDV.<id>.1.<standard>.<version>``.

    Examples:
        Build the OID::

            from fleet.core.oids import metadata_version_oid

            oid = metadata_version_oid("CDISCPILOT01", "SDTMIG", "3.4")
            assert oid == "MDV.CDISCPILOT01.1.SDTMIG.3.4"
    """
    return f"MDV.{study_id}.1.{standard}.{version}"
