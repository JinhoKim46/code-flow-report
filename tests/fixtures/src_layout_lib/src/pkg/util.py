def helper(x):
    from pkg.core import run  # lazy on purpose: avoids a module-level cycle
    return x if x else run
