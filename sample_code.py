def clamp(x, lo=0, hi=100):
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x

def mean(xs):
    return sum(xs) / len(xs)

def apply_discount(price, pct):
    if pct > 50:
        pct = 50
    return price - price * pct / 100
