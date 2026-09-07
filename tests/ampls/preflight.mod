var x >= 0 <= 2;
var z binary;

s.t. indicator_if_one: z = 1 ==> x <= 1;
s.t. indicator_if_zero: z = 0 ==> x <= 0;

minimize objective: (x - 2)^2 + 0.1 * z;
