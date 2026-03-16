export function bchart(input: { x: number[], target?: number, or_ratio?: number, limit?: number }) {
  const { x: xArr, or_ratio = 2.0, limit = 3.5 } = input;
  let { target } = input;
  const n = xArr.length;
  
  const p0 = target !== undefined ? (target > 1 ? (xArr.slice(0, target).reduce((a, b) => a + b, 0) / target) : target) 
                                 : (xArr.reduce((a, b) => a + b, 0) / n);
  
  if (p0 <= 0 || p0 >= 1) throw new Error("Target must be between 0 and 1.");
  
  const getp = (p: number, o: number) => (p * o) / (1 - p + p * o);
  const p1 = getp(p0, or_ratio);
  const p2 = getp(p0, 1 / or_ratio);
  
  const s1 = xArr.map(v => v * Math.log(p1 / p0) + (1 - v) * Math.log((1 - p1) / (1 - p0)));
  const s2 = xArr.map(v => v * Math.log(p2 / p0) + (1 - v) * Math.log((1 - p2) / (1 - p0)));
  
  const c1 = new Array(n).fill(0);
  const c2 = new Array(n).fill(0);
  const sig1 = new Array(n).fill(false);
  const sig2 = new Array(n).fill(false);
  
  let z1 = 0;
  let z2 = 0;
  const l2 = -limit;
  
  for (let i = 0; i < n; i++) {
    if (isNaN(s1[i])) {
      c1[i] = z1;
      c2[i] = z2;
      continue;
    }
    const z1i = z1 + s1[i];
    sig1[i] = z1i >= limit;
    c1[i] = (z1i > 0 && z1i <= limit) ? z1i : 0;
    z1 = c1[i];
    
    const z2i = z2 - s2[i];
    sig2[i] = z2i <= l2;
    c2[i] = (z2i < 0 && z2i >= l2) ? z2i : 0;
    z2 = c2[i];
  }
  
  const data = xArr.map((v, i) => ({
    x: i + 1,
    y: v,
    cusum_up: c1[i],
    cusum_down: c2[i],
    signal_up: sig1[i],
    signal_down: sig2[i],
    limit
  }));
  
  return {
    target: p0,
    or_ratio,
    limit,
    data,
    to_dict() {
      return {
        target: this.target,
        or_ratio: this.or_ratio,
        limit: this.limit,
        data: this.data
      };
    }
  };
}
