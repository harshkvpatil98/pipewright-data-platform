section Section1;

shared Customers = let
    Source = Csv.Document(File.Contents("C:\data\customers.csv"), [Delimiter=",", Columns=3, Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    #"Promoted Headers" = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    #"Changed Type" = Table.TransformColumnTypes(#"Promoted Headers", {{"customer_id", Int64.Type}, {"name", type text}, {"tier", type text}})
in
    #"Changed Type";

shared Orders = let
    Source = Excel.Workbook(File.Contents("C:\data\orders.xlsx"), null, true),
    Orders_Sheet = Source{[Item="Orders",Kind="Sheet"]}[Data],
    #"Changed Type" = Table.TransformColumnTypes(Orders_Sheet, {{"order_id", Int64.Type}, {"customer_id", Int64.Type}, {"amount", type number}, {"status", type text}}),
    // Cancelled orders and those with nothing to pay are left out.
    #"Filtered Rows" = Table.SelectRows(#"Changed Type", each [status] <> "cancelled" and [amount] > 0),
    #"Added Tax" = Table.AddColumn(#"Filtered Rows", "amount_with_tax", each [amount] * 1.2, type number),
    #"Upper Status" = Table.TransformColumns(#"Added Tax", {{"status", Text.Upper, type text}}),
    #"Merged Queries" = Table.NestedJoin(#"Upper Status", {"customer_id"}, Customers, {"customer_id"}, "Customers", JoinKind.LeftOuter),
    #"Expanded Customers" = Table.ExpandTableColumn(#"Merged Queries", "Customers", {"name", "tier"}, {"customer_name", "tier"}),
    #"Replaced Tier" = Table.ReplaceValue(#"Expanded Customers", null, "none", Replacer.ReplaceValue, {"tier"}),
    #"Added Band" = Table.AddColumn(#"Replaced Tier", "band", each if [amount] >= 100 then "large" else if [amount] >= 50 then "medium" else "small", type text),
    #"Sorted Rows" = Table.Sort(#"Added Band", {{"amount", Order.Descending}, {"order_id", Order.Ascending}})
in
    #"Sorted Rows";

shared Totals = let
    Source = Orders,
    #"Grouped Rows" = Table.Group(Source, {"tier"}, {{"orders", each Table.RowCount(_), Int64.Type}, {"revenue", each List.Sum([amount]), type number}, {"largest", each List.Max([amount]), type number}}),
    #"Renamed Columns" = Table.RenameColumns(#"Grouped Rows", {{"tier", "customer_tier"}})
in
    #"Renamed Columns";

shared Targets = #table({"tier", "target"}, {{"gold", 500}, {"silver", 200}, {"none", 50}});

shared Rounded = let
    Source = Orders,
    #"Rounded Off" = Table.TransformColumns(Source, {{"amount", each Number.Round(_, 0), type number}})
in
    #"Rounded Off";
