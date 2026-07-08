from fleet.adam.adsl_namespace import ADSLNamespace
from fleet.adam.namespace import AdamNamespace
from fleet.adam.occds_namespace import OCCDSNamespace
from fleet.sdtm.namespace import SDTMNamespace

class LazyFrame:
    @property
    def sdtm(self) -> SDTMNamespace: ...
    @property
    def adam(self) -> AdamNamespace: ...
    @property
    def adsl(self) -> ADSLNamespace: ...
    @property
    def occds(self) -> OCCDSNamespace: ...
