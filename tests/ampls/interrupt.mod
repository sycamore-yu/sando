set I := 1..120;
var y {I} binary;

maximize value: sum {i in I} (1 + (i mod 17)) * y[i];
s.t. capacity: sum {i in I} y[i] <= 60;
s.t. cover {j in 1..60}:
  sum {i in I: ((i + 3*j) mod 7) <= 2} y[i] <= 15;
