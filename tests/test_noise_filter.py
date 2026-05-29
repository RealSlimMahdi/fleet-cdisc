"""Quick test for _is_engine_noise logic."""
from fleet.validation.official import _is_engine_noise

# Always-noise patterns
assert _is_engine_noise("evaluation dataset failed to build", domain="EX")
assert _is_engine_noise("An unknown exception has occurred", domain="EX")

# Mentions our domain → NOT noise
assert not _is_engine_noise("Variable EXSEQ does not exist in dataset EX", domain="EX")
assert not _is_engine_noise("EX dataset is missing required variable", domain="EX")

# Cross-domain → IS noise
assert _is_engine_noise("DM dataset is missing", domain="EX")
assert _is_engine_noise("SUPPDM is not present in study", domain="EX")

# Generic findings → NOT noise
assert not _is_engine_noise("Variable EXSTDTC has invalid ISO format", domain="EX")
assert not _is_engine_noise("Required variable missing", domain="EX")

print("All noise filter assertions passed!")
