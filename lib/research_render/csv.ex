defmodule ResearchRender.CSV do
  alias NimbleCSV.RFC4180, as: CSV

  def read(path) do
    if File.regular?(path) do
      path
      |> File.read!()
      |> parse()
    else
      %{headers: [], rows: []}
    end
  rescue
    e -> raise "csv_parse_failed path=#{path} error=#{Exception.message(e)}"
  end

  def parse(content) do
    rows = CSV.parse_string(content, skip_headers: false)

    case rows do
      [] ->
        %{headers: [], rows: []}

      [headers | records] ->
        maps =
          Enum.map(records, fn record ->
            headers
            |> Enum.zip(record)
            |> Map.new()
          end)

        %{headers: headers, rows: maps}
    end
  end

  def write(path, headers, rows) do
    File.mkdir_p!(Path.dirname(path))

    body =
      [headers | Enum.map(rows, fn row -> Enum.map(headers, &Map.get(row, &1, "")) end)]
      |> CSV.dump_to_iodata()

    File.write!(path, body)
  end
end
