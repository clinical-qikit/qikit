# Reference fixtures: what the R packages qikit is checked against return on public data.
#
#   Rscript scripts/make_reference_fixtures.R [r_library]
#
# Writes fixtures/reference/*.json. Each file holds the input in qikit's terms and the
# R package's per-point (or per-provider) output, so tests/test_reference.py can compare
# without R. Re-run only when a reference package version changes; record the versions.
#
# Packages: qicharts2 (time-ordered charts and Anhoej run rules), FunnelPlotR (CQC and
# SHMI over-dispersion, arcsine proportions), NHSRplotthedots (NHS Making Data Count).
# NHSRplotthedots imports rsvg only to draw icons; on a machine without librsvg it can be
# installed from source with rsvg removed from Imports. Its statistics do not use it.

args <- commandArgs(trailingOnly = TRUE)
if (length(args) > 0) .libPaths(c(args[[1]], .libPaths()))

suppressPackageStartupMessages({
  library(jsonlite)
  library(qicharts2)
  library(FunnelPlotR)
  library(NHSRplotthedots)
})

out_dir <- file.path("fixtures", "reference")
dir.create(out_dir, showWarnings = FALSE, recursive = TRUE)

num <- function(v) ifelse(is.finite(v), v, NA)
versions <- function(...) {
  pk <- c(...)
  stats::setNames(lapply(pk, function(p) as.character(utils::packageVersion(p))), pk)
}
write_fixture <- function(name, obj) {
  writeLines(
    toJSON(obj, auto_unbox = TRUE, digits = NA, na = "null", null = "null", pretty = TRUE),
    file.path(out_dir, paste0(name, ".json"))
  )
}
iso <- function(d) if (inherits(d, "Date")) format(d, "%Y-%m-%d") else d

# ---------------------------------------------------------------------------
# qicharts2
# ---------------------------------------------------------------------------
qic_case <- function(name, input, call, description) {
  d <- call()
  parts <- split(d, d$part)
  write_fixture(name, list(
    source = "qicharts2",
    versions = versions("qicharts2"),
    description = description,
    input = input,
    expected = list(
      y = num(d$y), cl = num(d$cl), ucl = num(d$ucl), lcl = num(d$lcl),
      ucl_95 = num(d$ucl.95), lcl_95 = num(d$lcl.95),
      sigma_signal = as.logical(d$sigma.signal),
      part = as.integer(d$part),
      runs = lapply(parts, function(p) list(
        n_useful = p$n.useful[[1]],
        longest_run = p$longest.run[[1]],
        longest_run_max = p$longest.run.max[[1]],
        n_crossings = p$n.crossings[[1]],
        n_crossings_min = p$n.crossings.min[[1]],
        runs_signal = as.logical(p$runs.signal[[1]])
      ))
    )
  ))
}

cdi_in <- list(x = iso(cdi$month), y = cdi$n, n = cdi$days)
qic_case("qicharts2_run_cdi", c(cdi_in[c("x", "y")], chart = "run"),
         function() qic(month, n, data = cdi, return.data = TRUE),
         "Run chart of monthly C. difficile infections, 36 points; Anhoej rules.")
qic_case("qicharts2_run_cdi_part", c(cdi_in[c("x", "y")], chart = "run", part = 24),
         function() qic(month, n, data = cdi, part = 24, return.data = TRUE),
         "Run chart split after point 24: centre line and rules recomputed per part.")
qic_case("qicharts2_i_cdi_freeze", c(cdi_in[c("x", "y")], chart = "i", freeze = 24),
         function() qic(month, n, data = cdi, chart = "i", freeze = 24, return.data = TRUE),
         "I chart with limits frozen on the first 24 points.")
qic_case("qicharts2_c_cdi", c(cdi_in[c("x", "y")], chart = "c"),
         function() qic(month, n, data = cdi, chart = "c", return.data = TRUE),
         "C chart of monthly counts.")
qic_case("qicharts2_u_cdi", c(cdi_in, chart = "u", multiply = 10000),
         function() qic(month, n, days, data = cdi, chart = "u", multiply = 10000,
                        return.data = TRUE),
         "U chart, infections per 10,000 patient-days.")
qic_case("qicharts2_up_cdi", c(cdi_in, chart = "up", multiply = 10000),
         function() qic(month, n, days, data = cdi, chart = "up", multiply = 10000,
                        return.data = TRUE),
         "Laney u' chart on the same data.")
qic_case("qicharts2_i_cdi_rate", c(cdi_in, chart = "i", multiply = 10000),
         function() qic(month, n, days, data = cdi, chart = "i", multiply = 10000,
                        return.data = TRUE),
         "I chart of a rate: n= divides y on every chart type.")
qic_case("qicharts2_mr_cdi", c(cdi_in[c("x", "y")], chart = "mr"),
         function() qic(month, n, data = cdi, chart = "mr", return.data = TRUE),
         "Moving-range chart.")
acc_in <- list(x = nhs_accidents$i, y = nhs_accidents$r, n = nhs_accidents$n)
qic_case("qicharts2_p_accidents", c(acc_in, chart = "p"),
         function() qic(i, r, n, data = nhs_accidents, chart = "p", return.data = TRUE),
         "P chart with very large denominators (NHS A&E 4-hour standard).")
qic_case("qicharts2_pp_accidents", c(acc_in, chart = "pp"),
         function() qic(i, r, n, data = nhs_accidents, chart = "pp", return.data = TRUE),
         "Laney p' chart: the case it was designed for.")

small <- data.frame(x = 1:12, y = c(9, 8, 9, 10, 7, 9, 8, 10, 10, 9, 6, 10), n = 10)
qic_case("qicharts2_p_small_n", c(as.list(small), chart = "p"),
         function() qic(x, y, n, data = small, chart = "p", return.data = TRUE),
         "P chart at n = 10 and p near 0.9: the upper limit is capped at 1.")

cabg_m <- cabg
cabg_m$month <- as.Date(cut(cabg_m$date, "month"))
cabg_in <- list(x = iso(cabg_m$month), y = cabg_m$age)
qic_case("qicharts2_xbar_cabg", c(cabg_in, chart = "xbar"),
         function() qic(month, age, data = cabg_m, chart = "xbar", return.data = TRUE),
         "X-bar chart of patient age by month, unequal subgroup sizes.")
qic_case("qicharts2_s_cabg", c(cabg_in, chart = "s"),
         function() qic(month, age, data = cabg_m, chart = "s", return.data = TRUE),
         "S chart of patient age by month.")

ord <- cabg[order(cabg$date), ]
deaths <- which(ord$death)
g_y <- diff(c(0, deaths)) - 1
qic_case("qicharts2_g_cabg", list(x = seq_along(g_y), y = g_y, chart = "g"),
         function() qic(g_y, chart = "g", return.data = TRUE),
         "G chart: surgeries between deaths. Limits from the mean, centre line the median.")
t_y <- as.numeric(diff(ord$date[deaths]))
t_y <- t_y[t_y > 0]
qic_case("qicharts2_t_cabg", list(x = seq_along(t_y), y = t_y, chart = "t"),
         function() qic(t_y, chart = "t", return.data = TRUE),
         "T chart: days between deaths.")

# Run-rule thresholds across series lengths, on series built to sit near the boundary.
set.seed(20261101)
for (len in c(10, 12, 16, 20, 24, 30, 48)) {
  y <- round(rnorm(len), 3)
  run <- round(log2(len)) + 3
  y[seq_len(run)] <- abs(y[seq_len(run)]) + 2  # a run of exactly the published limit
  qic_case(sprintf("qicharts2_run_len%02d", len), list(x = seq_len(len), y = y, chart = "run"),
           function() qic(y, return.data = TRUE),
           sprintf("Run chart, n = %d, opening run of round(log2 n) + 3 points.", len))
}

# ---------------------------------------------------------------------------
# FunnelPlotR
# ---------------------------------------------------------------------------
data("medpar", package = "COUNT")
medpar$provnum <- as.character(medpar$provnum)
mod <- glm(died ~ age80 + factor(type), family = "binomial", data = medpar)
medpar$prds <- predict(mod, type = "response")
medpar$one <- 1
los_mod <- glm(los ~ age80 + factor(type), family = "poisson", data = medpar)
medpar$los_exp <- predict(los_mod, type = "response")

funnel_case <- function(name, numerator, denominator, data_type, sr_method, description) {
  # funnel_plot() quotes its column arguments, so the names are spliced in as symbols.
  fp <- funnel_plot(medpar, numerator = !!rlang::sym(numerator),
                    denominator = !!rlang::sym(denominator), group = provnum, data_type = data_type, sr_method = sr_method,
                    limit = 99, draw_unadjusted = TRUE, draw_adjusted = TRUE)
  agg <- source_data(fp)
  agg <- agg[order(agg$group), ]
  write_fixture(name, list(
    source = "FunnelPlotR",
    versions = versions("FunnelPlotR", "COUNT"),
    description = description,
    input = list(unit = as.character(agg$group), y = agg$numerator, n = agg$denominator,
                 data_type = data_type, sr_method = sr_method),
    expected = list(
      phi = phi(fp), tau2 = tau2(fp),
      od99_lcl = num(agg$OD99LCL), od99_ucl = num(agg$OD99UCL),
      od95_lcl = num(agg$OD95LCL), od95_ucl = num(agg$OD95UCL),
      outlier = as.logical(agg$outlier)
    )
  ))
}
funnel_case("funnelplotr_sr_shmi", "died", "prds", "SR", "SHMI",
            "Medicare deaths per provider against a logistic risk model; SHMI method.")
funnel_case("funnelplotr_sr_cqc", "died", "prds", "SR", "CQC",
            "The same data; CQC method (square-root scale, winsorized).")
funnel_case("funnelplotr_los_shmi", "los", "los_exp", "SR", "SHMI",
            "Length of stay (days) per provider against a Poisson model: over-dispersed; SHMI.")
funnel_case("funnelplotr_los_cqc", "los", "los_exp", "SR", "CQC",
            "Length of stay per provider; CQC method.")
funnel_case("funnelplotr_pr", "died", "one", "PR", "SHMI",
            "Crude proportion died per provider; arcsine scale, winsorized.")

# ---------------------------------------------------------------------------
# NHSRplotthedots
# ---------------------------------------------------------------------------
data("ae_attendances", package = "NHSRdatasets")
ptd_case <- function(name, org, improvement, target = NULL, fix = NULL, rebase = NULL) {
  d <- ae_attendances[ae_attendances$org_code == org & ae_attendances$type == "1", ]
  d <- d[order(d$period), ]
  s <- ptd_spc(d, value_field = "breaches", date_field = "period",
               improvement_direction = improvement, target = target,
               fix_after_n_points = fix,
               rebase = if (is.null(rebase)) NULL else d$period[[rebase]])
  s <- as.data.frame(s)
  write_fixture(name, list(
    source = "NHSRplotthedots",
    versions = versions("NHSRplotthedots", "NHSRdatasets"),
    description = sprintf("A&E 4-hour breaches, %s, type 1; improvement %s.", org, improvement),
    input = list(x = iso(d$period), y = d$breaches, improvement = improvement,
                 target = target, freeze = fix,
                 part = if (is.null(rebase)) NULL else as.integer(rebase - 1)),
    expected = list(
      cl = num(s$mean_col), ucl = num(s$upl), lcl = num(s$lpl),
      special_cause_type = s$special_cause_type,
      point_type = s$point_type,
      assurance_type = if (is.null(target)) NULL else {
        last <- s[nrow(s), ]
        if (target > last$upl) { if (improvement == "increase") "consistent_fail" else "consistent_pass" }
        else if (target < last$lpl) { if (improvement == "increase") "consistent_pass" else "consistent_fail" }
        else "inconsistent"
      }
    )
  ))
}
orgs <- names(sort(table(ae_attendances$org_code[ae_attendances$type == "1"]), decreasing = TRUE))
ptd_case("nhsrplotthedots_ae_a", orgs[[1]], "decrease")
ptd_case("nhsrplotthedots_ae_b", orgs[[2]], "decrease", target = 2000)
ptd_case("nhsrplotthedots_ae_c", orgs[[3]], "decrease", fix = 12)
ptd_case("nhsrplotthedots_ae_d", orgs[[4]], "increase", target = 100, rebase = 19)

cat("Wrote", length(list.files(out_dir, pattern = "json$")), "reference fixtures to", out_dir, "\n")
