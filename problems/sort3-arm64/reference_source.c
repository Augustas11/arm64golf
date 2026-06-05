void sort3(long long *out, long long a, long long b, long long c) {
    long long x = a;
    long long y = b;
    long long z = c;

    if (x > y) {
        long long t = x;
        x = y;
        y = t;
    }
    if (y > z) {
        long long t = y;
        y = z;
        z = t;
    }
    if (x > y) {
        long long t = x;
        x = y;
        y = t;
    }

    out[0] = x;
    out[1] = y;
    out[2] = z;
}
