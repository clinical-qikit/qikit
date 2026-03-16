export function paretochart(input: { x: string[] }) {
  const { x } = input;
  const counts: Record<string, number> = {};
  x.forEach(v => counts[v] = (counts[v] || 0) + 1);
  
  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const total = x.length;
  let cumSum = 0;
  
  const data = sorted.map(([category, count]) => {
    cumSum += count;
    return {
      category,
      count,
      cum_sum: cumSum,
      cum_percent: (cumSum / total) * 100
    };
  });
  
  return {
    data,
    to_dict() {
      return {
        data: this.data,
        ylab: 'Frequency'
      };
    }
  };
}
