# Regenerate Fleet's toxicity-grading criteria files from admiral metadata.
#
# Usage (from the repository root, with R and admiral installed):
#   Rscript scripts/regen_grading_criteria.R
#
# Each admiral table atoxgr_criteria_* becomes one JSON file under
# src/fleet/adam/grading/criteria/. GRADE_CRITERIA_CODE (an R case_when) and
# FILTER are parsed with R's own parser and written as expression trees, so the
# JSON holds the same rules as admiral. The admiral text of each term is kept
# under "source" for review. Do not edit the JSON files by hand: a Fleet rule
# that must differ from admiral goes in OVERRIDES below, with its reason.
#
# Expression nodes:
#   leaves  number | true | false | {"var": "AVAL"} | {"str": "M"} | {"param": "high_indicator"}
#   calls   {"op": OP, "args": [...]}; OP is one of
#           and or not is_na in lt le gt ge eq ne mul add sub neg signif
#           age (with "unit": "days" | "months" | "years"; args: start, end)

suppressMessages({
  library(admiral)
  library(jsonlite)
})

OUT_DIR <- file.path("src", "fleet", "adam", "grading", "criteria")
SCHEMA_VERSION <- 2L

FILES <- c(
  ctcae_v4 = "atoxgr_criteria_ctcv4",
  ctcae_v4_uscv = "atoxgr_criteria_ctcv4_uscv",
  ctcae_v5 = "atoxgr_criteria_ctcv5",
  ctcae_v5_uscv = "atoxgr_criteria_ctcv5_uscv",
  ctcae_v6 = "atoxgr_criteria_ctcv6",
  ctcae_v6_uscv = "atoxgr_criteria_ctcv6_uscv",
  daids = "atoxgr_criteria_daids",
  daids_uscv = "atoxgr_criteria_daids_uscv"
)

# Fleet deviations from admiral: list(system = list(TERM = function(entry) entry)).
# Each override must state its reason in a comment. None today.
OVERRIDES <- list()

OPS <- c(
  "&" = "and", "|" = "or", ">" = "gt", "<" = "lt", ">=" = "ge", "<=" = "le",
  "==" = "eq", "!=" = "ne", "*" = "mul"
)

flatten <- function(e, f) {
  if (is.call(e) && identical(as.character(e[[1]]), "(")) e <- e[[2]]
  if (is.call(e) && identical(as.character(e[[1]]), f)) {
    return(c(flatten(e[[2]], f), flatten(e[[3]], f)))
  }
  list(e)
}

conv <- function(e) {
  if (is.numeric(e)) {
    stopifnot(length(e) == 1, !is.na(e))
    return(unname(e))
  }
  if (is.character(e)) return(list(str = e))
  if (is.logical(e)) {
    stopifnot(length(e) == 1, !is.na(e))
    return(e)
  }
  if (is.name(e)) {
    s <- as.character(e)
    if (s %in% c("TRUE", "FALSE")) return(s == "TRUE")
    if (grepl("_indicator$", s)) return(list(param = s))
    return(list(var = s))
  }
  stopifnot(is.call(e))
  f <- as.character(e[[1]])
  a <- as.list(e)[-1]
  if (f == "(") return(conv(a[[1]]))
  if (f %in% c("&", "|")) {
    return(list(op = OPS[[f]], args = lapply(flatten(e, f), conv)))
  }
  if (f %in% names(OPS)) return(list(op = OPS[[f]], args = lapply(a, conv)))
  if (f == "!") return(list(op = "not", args = list(conv(a[[1]]))))
  if (f == "is.na") return(list(op = "is_na", args = list(conv(a[[1]]))))
  if (f == "%in%") return(list(op = "in", args = lapply(a, conv)))
  if (f == "+") {
    if (length(a) == 1) return(conv(a[[1]]))
    return(list(op = "add", args = lapply(a, conv)))
  }
  if (f == "-") {
    if (length(a) == 1) {
      x <- conv(a[[1]])
      if (is.numeric(x)) return(-x)
      return(list(op = "neg", args = list(x)))
    }
    return(list(op = "sub", args = lapply(a, conv)))
  }
  if (f == "signif") {
    if (!identical(a[[2]], quote(signif_dig))) stop("signif() without signif_dig: ", deparse(e))
    return(list(op = "signif", args = list(conv(a[[1]]))))
  }
  if (f == "compute_duration") {
    if (!isTRUE(a$trunc_out) || !isFALSE(a$add_one)) stop("unsupported compute_duration: ", deparse(e))
    unit <- a$out_unit
    if (!unit %in% c("days", "months", "years")) stop("unsupported unit: ", unit)
    type <- if (is.null(a$type)) "duration" else a$type
    if (unit != "days" && type != "interval") stop("unsupported type: ", deparse(e))
    return(list(op = "age", unit = unit, args = list(conv(a$start_date), conv(a$end_date))))
  }
  stop("unsupported call ", f, ": ", deparse(e))
}

conv_case_when <- function(code) {
  e <- parse(text = code)[[1]]
  # A subgroup that DAIDS does not grade holds the code NA_character_: no arm, null grade.
  if (identical(e, quote(NA_character_))) return(list())
  stopifnot(identical(as.character(e[[1]]), "case_when"))
  lapply(as.list(e)[-1], function(arm) {
    stopifnot(identical(as.character(arm[[1]]), "~"))
    value <- arm[[3]]
    then <- if (identical(value, quote(NA_character_))) NULL else value
    if (!is.null(then) && !(is.character(then) && then %in% c("0", "1", "2", "3", "4"))) {
      stop("unsupported case_when value: ", deparse(value))
    }
    list(when = one_line(conv(arm[[2]])), then = then)
  })
}

one_line <- function(node) {
  structure(toJSON(node, auto_unbox = TRUE, digits = NA), class = "json")
}

text_or_null <- function(row, col) {
  if (!col %in% names(row)) return(NULL)
  v <- row[[col]]
  if (is.na(v)) NULL else v
}

for (system in names(FILES)) {
  dataset <- FILES[[system]]
  meta <- getExportedValue("admiral", dataset)
  criteria <- lapply(seq_len(nrow(meta)), function(i) {
    row <- meta[i, ]
    filter_code <- text_or_null(row, "FILTER")
    entry <- list(
      term = row$TERM,
      direction = row$DIRECTION,
      unit = text_or_null(row, "UNIT_CHECK"),
      required_vars = I(trimws(strsplit(row$VAR_CHECK, ",")[[1]])),
      subgroup = text_or_null(row, "SUBGROUP"),
      filter = if (is.null(filter_code)) NULL else one_line(conv(parse(text = filter_code)[[1]])),
      arms = conv_case_when(row$GRADE_CRITERIA_CODE),
      source = list(
        soc = text_or_null(row, "SOC"),
        grade_1 = text_or_null(row, "GRADE_1"),
        grade_2 = text_or_null(row, "GRADE_2"),
        grade_3 = text_or_null(row, "GRADE_3"),
        grade_4 = text_or_null(row, "GRADE_4"),
        grade_5 = text_or_null(row, "GRADE_5"),
        comment = text_or_null(row, "COMMENT"),
        grade_criteria_code = row$GRADE_CRITERIA_CODE,
        filter = filter_code
      )
    )
    override <- OVERRIDES[[system]][[row$TERM]]
    if (!is.null(override)) entry <- override(entry)
    entry
  })
  out <- list(
    schema_version = SCHEMA_VERSION,
    version = sub("_uscv$", "", system),
    unit_system = if (grepl("_uscv$", system)) "USCV" else "SI",
    source = list(
      package = "admiral",
      package_version = as.character(packageVersion("admiral")),
      dataset = dataset,
      generated_by = "scripts/regen_grading_criteria.R"
    ),
    criteria = criteria
  )
  path <- file.path(OUT_DIR, paste0(system, ".json"))
  json <- toJSON(
    out,
    auto_unbox = TRUE, null = "null", digits = NA, pretty = 2, json_verbatim = TRUE
  )
  writeLines(json, path, useBytes = TRUE)
  cat(sprintf("%-14s %3d terms -> %s\n", system, length(criteria), path))
}
