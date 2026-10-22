def add_tag(tag: str, tags: list = []) -> list:  # expect: static_analysis
    tags.append(tag)
    return tags


def summarize(orders):
    total = 0
    unused_discount = 0.1  # expect: static_analysis
    for order in orders:
        total += order["amount"]
    return total
