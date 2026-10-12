"""Demo tool module for tool-call-replay (pure functions, no I/O, no network)."""


def add(a, b):
    return a + b


def greet(name):
    return "hello, %s!" % name


def slugify(s):
    return "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-")


def bounded_scale(x, factor=2.0):
    if factor > 100:
        raise ValueError("factor too large: %r" % (factor,))
    return x * factor


def fail():
    raise ValueError("boom")


TOOLS = {
    "add": add,
    "greet": greet,
    "slugify": slugify,
    "bounded_scale": bounded_scale,
    "fail": fail,
}
