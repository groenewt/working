defmodule ResearchRender.YAML do
  def read(path) do
    path
    |> File.read!()
    |> parse()
  rescue
    e -> raise "yaml_parse_failed path=#{path} error=#{Exception.message(e)}"
  end

  def parse(content) do
    YamlElixir.read_from_string!(content) || %{}
  end

  def dump(map) do
    encode_value(map, 0)
  end

  def scalar_locations(content) do
    content
    |> String.split("\n")
    |> Enum.with_index(1)
    |> Enum.reduce(%{}, fn {line, index}, acc ->
      case Regex.run(~r/^(\s*)([A-Za-z0-9_.-]+):(?:\s|$)/, line) do
        [_, indent, key] ->
          depth = div(String.length(indent), 2)
          Map.put_new(acc, key_path(acc, depth, key), index)

        _ ->
          acc
      end
    end)
  rescue
    _ -> %{}
  end

  defp key_path(acc, depth, key) do
    parent =
      acc
      |> Map.keys()
      |> Enum.filter(&(Enum.count(String.split(&1, ".")) == depth))
      |> List.last()

    if parent && depth > 0, do: parent <> "." <> key, else: key
  end

  defp encode_value(value, indent) when is_map(value) do
    value
    |> Enum.map(fn {key, child} ->
      prefix = String.duplicate(" ", indent) <> to_string(key) <> ":"

      if scalar?(child) do
        prefix <> " " <> encode_scalar(child) <> "\n"
      else
        prefix <> "\n" <> encode_value(child, indent + 2)
      end
    end)
    |> Enum.join()
  end

  defp encode_value(value, indent) when is_list(value) do
    value
    |> Enum.map(fn child ->
      prefix = String.duplicate(" ", indent) <> "-"

      if scalar?(child) do
        prefix <> " " <> encode_scalar(child) <> "\n"
      else
        prefix <> "\n" <> encode_value(child, indent + 2)
      end
    end)
    |> Enum.join()
  end

  defp encode_value(value, indent) do
    String.duplicate(" ", indent) <> encode_scalar(value) <> "\n"
  end

  defp scalar?(value), do: not (is_map(value) or is_list(value))

  defp encode_scalar(nil), do: "null"
  defp encode_scalar(true), do: "true"
  defp encode_scalar(false), do: "false"
  defp encode_scalar(value) when is_integer(value) or is_float(value), do: to_string(value)

  defp encode_scalar(value) do
    string = to_string(value)

    cond do
      string == "" ->
        ~s("")

      String.contains?(string, "\n") ->
        "|\n" <>
          (string
           |> String.split("\n")
           |> Enum.map_join("\n", &("  " <> &1)))

      Regex.match?(~r/[:#\[\]\{\},&*!|>'"%@`]/, string) or String.trim(string) != string ->
        inspect(string)

      true ->
        string
    end
  end
end
