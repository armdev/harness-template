# expect: unused function


def used():
    return 1


def forgotten_helper():
    return 2


print(used())
