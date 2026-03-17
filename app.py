import streamlit as st
import pandas as pd
from qikit.spc import qic
from qikit.doe import design, analyze, ExperimentDesign
from typing import List, Optional

st.set_page_config(
    page_title="QIKit Data Analysis",
    page_icon="📈",
    layout="wide"
)

# --- Helper Functions ---
@st.cache_data
def load_data(uploaded_file) -> Optional[pd.DataFrame]:
    if uploaded_file is None:
        return None
    try:
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        elif uploaded_file.name.endswith('.xlsx'):
            df = pd.read_excel(uploaded_file)
        else:
            st.error("Unsupported file type.")
            return None
        return df
    except Exception as e:
        st.error(f"Error loading file: {e}")
        return None

def guess_column(df: pd.DataFrame, possible_names: List[str]) -> str:
    """Returns the first column matching a list of possible names (case-insensitive)."""
    df_cols = [c.lower() for c in df.columns]
    for name in possible_names:
        if name.lower() in df_cols:
            return df.columns[df_cols.index(name.lower())]
    return ""

# --- Main App ---
st.title("📈 QIKit Analysis Platform")

tab_spc, tab_doe = st.tabs(["📈 SPC Charts", "🧪 Design of Experiments (DOE)"])

# =====================================================================
# SPC TAB
# =====================================================================
with tab_spc:
    st.markdown("Upload your data to automatically generate Statistical Process Control (SPC) charts.")
    
    col_upload, col_main = st.columns([1, 3])
    
    with col_upload:
        st.header("1. Upload Data")
        spc_file = st.file_uploader("Upload CSV or Excel file", type=['csv', 'xlsx'], key="spc_file")
        
        if spc_file is not None:
            df_spc = load_data(spc_file)
            
            st.header("2. Map Columns")
            cols = [""] + list(df_spc.columns)
            
            default_x = guess_column(df_spc, ['date', 'time', 'month', 'year', 'x', 'period'])
            default_y = guess_column(df_spc, ['value', 'y', 'measure', 'count', 'numerator'])
            default_n = guess_column(df_spc, ['n', 'denominator', 'size', 'total'])
            
            col_x = st.selectbox("X-Axis (Time/Sequence)", cols, index=cols.index(default_x) if default_x in cols else 0, key="spc_x")
            col_y = st.selectbox("Y-Axis (Measure)", cols, index=cols.index(default_y) if default_y in cols else 0, key="spc_y")
            col_n = st.selectbox("N (Denominator/Size)", cols, index=cols.index(default_n) if default_n in cols else 0, help="Required for P, U charts", key="spc_n")
            col_facets = st.selectbox("Facets (Stratification)", cols, index=0, key="spc_facets")
            col_part = st.selectbox("Part (Phases/Shifts)", cols, index=0, key="spc_part")
            col_notes = st.selectbox("Notes (Annotations)", cols, index=0, key="spc_notes")
            
            st.header("3. Chart Configuration")
            chart_type = st.selectbox("Chart Type", ["run", "i", "mr", "xbar", "s", "t", "p", "pp", "c", "u", "up", "g"], key="spc_type")
            method = st.selectbox("Signal Method", ["anhoej", "ihi", "weco", "nelson"], key="spc_method")
            
            freeze = st.number_input("Freeze Baseline (Index)", min_value=0, value=0, key="spc_freeze")
            exclude = st.text_input("Exclude (Indices)", value="", help="Comma separated", key="spc_exclude")
            
            st.header("4. Aesthetics")
            title = st.text_input("Chart Title", value="SPC Chart", key="spc_title")
            ylab = st.text_input("Y-Axis Label", value=col_y if col_y else "Value", key="spc_ylab")
            xlab = st.text_input("X-Axis Label", value=col_x if col_x else "Subgroup", key="spc_xlab")
            
    with col_main:
        if spc_file is not None and df_spc is not None:
            with st.expander("Preview Raw Data"):
                st.dataframe(df_spc.head())
                
            if st.button("Generate SPC Chart", type="primary", key="spc_btn"):
                if not col_x or not col_y:
                    st.error("Please select both X and Y columns.")
                else:
                    try:
                        freeze_val = int(freeze) if freeze > 0 else None
                        exclude_val = [int(i.strip()) for i in exclude.split(',')] if exclude else None
                        
                        kwargs = {
                            "data": df_spc, "x": col_x, "y": col_y,
                            "chart": chart_type, "method": method,
                            "title": title, "ylab": ylab, "xlab": xlab
                        }
                        if col_n: kwargs["n"] = col_n
                        if col_facets: kwargs["facets"] = col_facets
                        if col_part: kwargs["part"] = col_part
                        if col_notes: kwargs["notes"] = col_notes
                        if freeze_val is not None: kwargs["freeze"] = freeze_val
                        if exclude_val: kwargs["exclude"] = exclude_val

                        with st.spinner("Computing..."):
                            result = qic(**kwargs)
                            
                        st.plotly_chart(result.plot(), use_container_width=True)
                        
                        col_stat, col_data = st.columns(2)
                        with col_stat:
                            st.subheader("Analysis Summary")
                            st.write(result.summary)
                        with col_data:
                            st.subheader("Computed Data")
                            st.dataframe(result.data.head(10))
                            st.download_button(
                                "Download Full Results",
                                data=result.data.to_csv(index=False).encode('utf-8'),
                                file_name='spc_results.csv', mime='text/csv'
                            )
                    except Exception as e:
                        st.error(f"Computation failed: {e}")
        else:
            st.info("👈 Upload data on the left to get started with SPC.")

# =====================================================================
# DOE TAB
# =====================================================================
with tab_doe:
    st.markdown("Design and analyze experimental data to identify key driving factors.")
    
    doe_mode = st.radio("DOE Mode", ["1. Create New Design", "2. Analyze Results"], horizontal=True)
    
    if "1" in doe_mode:
        st.header("Create a New Experimental Design")
        st.markdown("Specify your factors to generate a standard test matrix. Download it, fill in the 'Response' column after running your experiments, and upload it back in the Analyze tab.")
        
        col1, col2 = st.columns([1, 2])
        with col1:
            num_factors = st.number_input("Number of Factors", min_value=1, max_value=7, value=3)
            factors = []
            for i in range(int(num_factors)):
                factors.append(st.text_input(f"Factor {i+1} Name", value=chr(65+i)))
                
            design_type = st.selectbox("Design Type", ["full_factorial", "fractional", "one_factor"])
            replicates = st.number_input("Replicates", min_value=1, value=1)
            center_points = st.number_input("Center Points", min_value=0, value=0)
            
            if st.button("Generate Design Matrix", type="primary"):
                try:
                    d = design(factors=factors, design_type=design_type, replicates=replicates, center_points=center_points)
                    st.session_state['doe_design'] = d
                except Exception as e:
                    st.error(f"Error generating design: {e}")
                    
        with col2:
            if 'doe_design' in st.session_state:
                st.success(f"Generated {st.session_state['doe_design'].n_runs} runs.")
                st.dataframe(st.session_state['doe_design'].matrix)
                st.download_button(
                    "Download Design CSV", 
                    data=st.session_state['doe_design'].matrix.to_csv(index=False).encode('utf-8'),
                    file_name="doe_design.csv", mime="text/csv"
                )
                
    else:
        st.header("Analyze Experimental Results")
        col_upload_doe, col_main_doe = st.columns([1, 3])
        
        with col_upload_doe:
            doe_file = st.file_uploader("Upload Completed Design (CSV/Excel)", type=['csv', 'xlsx'], key="doe_file")
            
            if doe_file:
                df_doe = load_data(doe_file)
                all_cols = list(df_doe.columns)
                
                resp_guess = guess_column(df_doe, ['response', 'yield', 'y', 'output', 'result'])
                response_col = st.selectbox("Response Column", all_cols, index=all_cols.index(resp_guess) if resp_guess in all_cols else len(all_cols)-1)
                
                # Default factor columns guess (exclude known non-factors)
                exclude_from_factors = ['RunOrder', 'StandardOrder', response_col]
                default_factors = [c for c in all_cols if c not in exclude_from_factors]
                factor_cols = st.multiselect("Factor Columns", [c for c in all_cols if c != response_col], default=default_factors)
                
                plot_type = st.selectbox("Plot Type", ["effects", "interaction", "cube", "run_order", "dot_diagram"])
                
                analyze_btn = st.button("Analyze Experiment", type="primary")
        
        with col_main_doe:
            if doe_file and df_doe is not None:
                with st.expander("Preview Raw Data"):
                    st.dataframe(df_doe.head())
                    
                if analyze_btn:
                    if not factor_cols or not response_col:
                        st.error("Please select at least one factor and a response column.")
                    else:
                        try:
                            # 1. Standardize factors to -1, +1 for correct effect sizing
                            coded_matrix = df_doe[factor_cols].copy()
                            for col in factor_cols:
                                # Simple min/max normalization to -1, 1 if numeric and varying
                                if pd.api.types.is_numeric_dtype(coded_matrix[col]):
                                    min_val, max_val = coded_matrix[col].min(), coded_matrix[col].max()
                                    if min_val != max_val:
                                        mean_val = (max_val + min_val) / 2
                                        range_val = (max_val - min_val) / 2
                                        coded_matrix[col] = (coded_matrix[col] - mean_val) / range_val
                                    else:
                                        coded_matrix[col] = 1.0 # Constant factor
                                        
                            full_matrix = df_doe.copy()
                            for col in factor_cols: full_matrix[col] = coded_matrix[col]
                            if 'RunOrder' not in full_matrix.columns:
                                full_matrix.insert(0, 'RunOrder', range(1, len(full_matrix) + 1))
                                
                            # 2. Build the ExperimentDesign container dynamically
                            d = ExperimentDesign(
                                factors=tuple(factor_cols),
                                lows=tuple([-1]*len(factor_cols)),
                                highs=tuple([1]*len(factor_cols)),
                                design_type="full_factorial", 
                                matrix=full_matrix,
                                n_factors=len(factor_cols),
                                n_runs=len(full_matrix),
                                n_replicates=1,
                                n_center_points=0,
                                generators=None,
                                resolution=None
                            )
                            
                            # 3. Analyze
                            res = analyze(d, full_matrix[response_col].values)
                            
                            # 4. Display Results
                            st.plotly_chart(res.plot(chart=plot_type), use_container_width=True)
                            
                            col_s1, col_s2 = st.columns(2)
                            with col_s1:
                                st.subheader("Model Summary")
                                st.metric("R² (Explained Variance)", f"{res.r_squared:.3f}")
                                st.metric("Adjusted R²", f"{res.adj_r_squared:.3f}")
                            with col_s2:
                                st.subheader("Effects Table")
                                st.dataframe(res.effects[['term', 'effect', 'pct_contribution']])
                                
                        except Exception as e:
                            st.error(f"Analysis failed: {e}")
            else:
                st.info("👈 Upload your completed design matrix to analyze effects.")
