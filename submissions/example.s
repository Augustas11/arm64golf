// Worked example for the open-submission contestant track.
// This is the existing reference baseline; submitting it again should dedup
// against the seed baseline receipt.
//
// sort3-arm64 canonical v0.1 baseline.
// ABI: signed int64 inputs in x0, x1, x2; ascending outputs in x0, x1, x2.
// Shape: textbook three-comparator sorting network, expanded as bitmask
// conditional swaps for a stable 18-instruction starting point.

cmp x0, x1
csetm x3, gt
eor x4, x0, x1
and x4, x4, x3
eor x0, x0, x4
eor x1, x1, x4

cmp x1, x2
csetm x3, gt
eor x4, x1, x2
and x4, x4, x3
eor x1, x1, x4
eor x2, x2, x4

cmp x0, x1
csetm x3, gt
eor x4, x0, x1
and x4, x4, x3
eor x0, x0, x4
eor x1, x1, x4
