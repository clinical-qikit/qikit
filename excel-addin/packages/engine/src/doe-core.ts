export type DesignType = 'full_factorial' | 'fractional' | 'one_factor';

export interface DOEDesign {
  factors: string[];
  lows: number[];
  highs: number[];
  design_type: DesignType;
  matrix: Array<Record<string, any>>;
  n_factors: number;
  n_runs: number;
  n_replicates: number;
  n_center_points: number;
  generators?: string[];
  resolution?: number;
}

export interface DOEResult {
  design: DOEDesign;
  response: number[];
  effects: Array<Record<string, any>>;
  grand_mean: number;
  r_squared: number;
  adj_r_squared: number;
  summary: Record<string, any>;
  to_dict(): Record<string, any>;
}

const GENERATORS: Record<string, [string[], number]> = {
  '3,1': [['C=AB'], 3],
  '4,1': [['D=ABC'], 4],
  '5,1': [['E=ABCD'], 5],
  '5,2': [['D=AB', 'E=AC'], 3],
  '6,1': [['F=ABCDE'], 6],
  '6,2': [['E=ABC', 'F=BCD'], 4],
  '6,3': [['D=AB', 'E=AC', 'F=BC'], 3],
  '7,1': [['G=ABCDEF'], 7],
  '7,2': [['F=ABCD', 'G=ABDE'], 4],
  '7,3': [['E=ABC', 'F=BCD', 'G=ACD'], 4],
  '7,4': [['D=AB', 'E=AC', 'F=BC', 'G=ABC'], 3],
  '8,1': [['H=ABCDEFG'], 8],
  '8,4': [['E=BCD', 'F=ACD', 'G=ABC', 'H=ABD'], 4],
  '15,11': [['E=ABCD', 'F=ABC', 'G=ABD', 'H=ACD', 'I=BCD', 'J=AB', 'K=AC', 'L=AD', 'M=BC', 'N=BD', 'O=CD'], 3],
  '16,11': [['F=ABCDE', 'G=ABCD', 'H=ABCE', 'I=ABDE', 'J=ACDE', 'K=BCDE', 'L=ABC', 'M=ABD', 'N=ACD', 'O=BCD', 'P=ABCDE'], 3],
};

function yatesMatrix(k: number): number[][] {
  const n = Math.pow(2, k);
  const matrix: number[][] = Array.from({ length: n }, () => new Array(k));
  for (let j = 0; j < k; j++) {
    const blockSize = Math.pow(2, j);
    for (let i = 0; i < n; i++) {
      matrix[i][j] = Math.floor(i / blockSize) % 2 === 0 ? -1 : 1;
    }
  }
  return matrix;
}

function fractionalMatrix(k: number, p: number, generators: string[]): number[][] {
  const baseK = k - p;
  const base = yatesMatrix(baseK);
  const factorLabels = Array.from({ length: k }, (_, i) => String.fromCharCode(65 + i));
  const baseLabels = factorLabels.slice(0, baseK);
  
  const matrix: number[][] = base.map(row => [...row]);
  
  for (const gen of generators) {
    const [target, sources] = gen.replace(/\s/g, '').split('=');
    const sourceIndices = sources.split('').map(s => baseLabels.indexOf(s));
    
    for (let i = 0; i < base.length; i++) {
      let val = 1;
      for (const idx of sourceIndices) val *= base[i][idx];
      matrix[i].push(val);
    }
  }
  
  return matrix;
}

export function design(input: {
  factors: string[],
  lows?: number[],
  highs?: number[],
  design_type?: DesignType,
  generators?: string[],
  replicates?: number,
  center_points?: number,
  randomize?: 'none' | 'full',
  seed?: number
}): DOEDesign {
  const { factors, lows = new Array(factors.length).fill(-1), highs = new Array(factors.length).fill(1), 
          design_type = 'full_factorial', replicates = 1, center_points = 0 } = input;
  let { generators } = input;
  const k = factors.length;
  let matrix: number[][] = [];
  let resolution: number | undefined = undefined;

  if (design_type === 'full_factorial') {
    matrix = yatesMatrix(k);
  } else if (design_type === 'fractional') {
    let p = 0;
    if (generators) {
      p = generators.length;
    } else {
      const availableP = Object.keys(GENERATORS).filter(key => key.startsWith(`${k},`)).map(key => parseInt(key.split(',')[1]));
      if (availableP.length === 0) throw new Error(`No standard generators for k=${k}`);
      p = Math.max(...availableP);
      [generators, resolution] = GENERATORS[`${k},${p}`];
    }
    matrix = fractionalMatrix(k, p, generators!);
  } else if (design_type === 'one_factor') {
    matrix = [new Array(k).fill(-1)];
    for (let i = 0; i < k; i++) {
      const row = new Array(k).fill(-1);
      row[i] = 1;
      matrix.push(row);
    }
  }

  // Replicate
  let finalMatrix = [];
  for (let r = 0; r < replicates; r++) {
      for (const row of matrix) finalMatrix.push([...row]);
  }

  // Center points
  for (let c = 0; c < center_points; c++) {
    finalMatrix.push(new Array(k).fill(0));
  }

  const nRuns = finalMatrix.length;
  const resMatrix = finalMatrix.map((row, i) => {
    const obj: Record<string, any> = { RunOrder: i + 1 };
    factors.forEach((f, j) => obj[f] = row[j]);
    obj.Response = null;
    return obj;
  });

  return {
    factors, lows, highs, design_type,
    matrix: resMatrix,
    n_factors: k,
    n_runs: nRuns,
    n_replicates: replicates,
    n_center_points: center_points,
    generators,
    resolution
  };
}

export function analyze(designObj: DOEDesign, response: number[], maxInteraction: number = 2): DOEResult {
  if (response.length !== designObj.n_runs) throw new Error("Response length mismatch");
  
  const n = response.length;
  const yBar = response.reduce((a, b) => a + b, 0) / n;
  const ssTotal = response.reduce((a, b) => a + Math.pow(b - yBar, 2), 0);
  
  const factorNames = designObj.factors;
  const codedMatrix = designObj.matrix.map(row => factorNames.map(f => row[f]));
  
  const terms: any[] = [];
  
  // Helper to get combinations
  function* combinations(arr: number[], size: number): Generator<number[]> {
    if (size === 0) yield [];
    else {
      for (let i = 0; i < arr.length; i++) {
        for (const rest of combinations(arr.slice(i + 1), size - 1)) {
          yield [arr[i], ...rest];
        }
      }
    }
  }

  for (let order = 1; order <= maxInteraction; order++) {
    const indices = Array.from({ length: factorNames.length }, (_, i) => i);
    for (const combo of combinations(indices, order)) {
      const termLabel = combo.map(i => factorNames[i]).join(':');
      
      let dot = 0;
      for (let i = 0; i < n; i++) {
        let contrast = 1;
        for (const idx of combo) contrast *= codedMatrix[i][idx];
        dot += contrast * response[i];
      }
      
      const effect = 2.0 * dot / n;
      const ss = (effect * effect * n) / 4.0;
      const pct = ssTotal > 0 ? (100.0 * ss / ssTotal) : 0;
      
      terms.push({
        term: termLabel,
        effect,
        abs_effect: Math.abs(effect),
        ss,
        pct_contribution: pct,
        _combo: combo
      });
    }
  }

  const ssModel = terms.reduce((a, b) => a + b.ss, 0);
  const rSquared = ssTotal > 0 ? ssModel / ssTotal : 0;
  
  const p = terms.length;
  const adjRSquared = n > p + 1 ? (1.0 - (1.0 - rSquared) * (n - 1) / (n - p - 1)) : 0;

  return {
    design: designObj,
    response,
    effects: terms,
    grand_mean: yBar,
    r_squared: rSquared,
    adj_r_squared: adjRSquared,
    summary: { n_runs: n, n_factors: designObj.n_factors, ss_total: ssTotal },
    to_dict() {
      return {
        design: this.design,
        response: this.response,
        effects: this.effects.map(t => {
            const { _combo, ...rest } = t;
            return rest;
        }),
        grand_mean: this.grand_mean,
        r_squared: this.r_squared,
        adj_r_squared: this.adj_r_squared,
        summary: this.summary
      };
    }
  };
}
