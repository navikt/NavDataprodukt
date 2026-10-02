#' Fetch Data from DVH
#'
#' Executes a query against the established database connection.
#'
#' @param connection A DBIConnection object created by `db_connect()`.
#' @param query Character string containing the SQL query.
#'
#' @return A data frame.
#' @export
#'
#' @importFrom DBI dbGetQuery

hent_data <- function(connection, query = "") {
  if (!DBI::dbIsValid(connection)) {
    stop("Feil i databaseconnection.")
  }

  data <- DBI::dbGetQuery(connection, query, encoding = "latin1")
  return(data)
}
