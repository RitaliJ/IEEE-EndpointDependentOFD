import numpy as np
import random

rng: random.Random = random.Random(42)

order_timings: list[float] = (
        np.random.default_rng(rng.randint(0, 2**32 - 1))
        .poisson(lam=1, size=5)
        .tolist()
    )


inter_arrivals = (
        np.random.default_rng(rng.randint(0, 2**32 - 1))
        .exponential(scale=1.0 / 1, size=5)
    )
order_timings: list[float] = np.cumsum(inter_arrivals).tolist()

print(order_timings)