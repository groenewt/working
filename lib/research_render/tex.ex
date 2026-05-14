defmodule ResearchRender.TeX do
  def tex(value) do
    value
    |> to_string()
    |> ascii_tex_source()
    |> String.replace(~r/[\\&%$#_{}~^]/, fn char ->
      case char do
        "\\" -> "\\textbackslash{}"
        "&" -> "\\&"
        "%" -> "\\%"
        "$" -> "\\$"
        "#" -> "\\#"
        "_" -> "\\_"
        "{" -> "\\{"
        "}" -> "\\}"
        "~" -> "\\textasciitilde{}"
        "^" -> "\\textasciicircum{}"
      end
    end)
  end

  def ascii_tex_source(value) do
    value
    |> String.graphemes()
    |> Enum.map(fn char ->
      case char do
        "\n" -> char
        "\t" -> char
        "\r" -> char
        _ ->
          [codepoint | _] = String.to_charlist(char)

          if codepoint in 32..126 do
            char
          else
            "[U+#{codepoint |> Integer.to_string(16) |> String.upcase() |> String.pad_leading(4, "0")}]"
          end
      end
    end)
    |> Enum.join()
  end

  def code(value), do: "\\begingroup\\ttfamily #{code_line(value)}\\endgroup{}"

  def code_line(value), do: value |> tex() |> breakable_tex()

  def breakable_tex(rendered_value) do
    rendered_value
    |> String.replace("\\_", "\\_\\allowbreak{}")
    |> String.replace("/", "/\\allowbreak{}")
    |> String.replace(".", ".\\allowbreak{}")
    |> String.replace("-", "-\\allowbreak{}")
    |> String.replace(":", ":\\allowbreak{}")
    |> String.replace("=", "=\\allowbreak{}")
    |> String.replace("+", "+\\allowbreak{}")
    |> String.replace("*", "*\\allowbreak{}")
    |> String.replace(";", ";\\allowbreak{}")
    |> String.replace(",", ",\\allowbreak{}")
    |> String.replace("|", "|\\allowbreak{}")
    |> String.replace("[", "[\\allowbreak{}")
    |> String.replace("]", "]\\allowbreak{}")
    |> String.replace("(", "(\\allowbreak{}")
    |> String.replace(")", ")\\allowbreak{}")
    |> String.replace("\\{", "\\{\\allowbreak{}")
    |> String.replace("\\}", "\\}\\allowbreak{}")
    |> String.replace(~r/(?<=[a-z0-9])(?=[A-Z])/, "\\allowbreak{}")
  end

  def heading(ctx, _appendix, level, title, label) do
    command = Enum.at(ctx.table_levels, min(level, length(ctx.table_levels) - 1))
    after_heading = if level >= 3, do: "\n\\mbox{}\\par", else: ""
    "#{command}{#{title |> tex() |> breakable_tex()}}\n\\label{#{label}}#{after_heading}"
  end

  def provenance_line(value), do: "{\\scriptsize #{value}\\par}"
end
