# Load custom standalone models first so their ORM names are registered
# before inherited extensions reference them as comodels.
from . import custom
from . import inherited
