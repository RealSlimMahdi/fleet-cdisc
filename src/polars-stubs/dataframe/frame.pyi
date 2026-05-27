from fleet.adam.namespace import AdamNamespace
from fleet.sdtm.namespace import SDTMNamespace
from fleet.tlg.namespace import TLGNamespace

class DataFrame:
    @property
    def sdtm(self) -> SDTMNamespace: ...
    @property
    def adam(self) -> AdamNamespace: ...
    @property
    def tlg(self) -> TLGNamespace: ...
