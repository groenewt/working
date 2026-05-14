defmodule Mix.Tasks.Research.Render do
  use Mix.Task

  @shortdoc "Render research appendices and the DuckDB projection"

  @impl Mix.Task
  def run(args) do
    Mix.Task.run("app.start")

    {opts, _argv, invalid} =
      OptionParser.parse(args,
        strict: [
          repo_root: :string,
          mode: :string
        ]
      )

    unless invalid == [] do
      ResearchRender.CLI.abort!("invalid_options #{inspect(invalid)}")
    end

    repo_root =
      opts
      |> Keyword.get(:repo_root, File.cwd!())
      |> Path.expand()

    mode = Keyword.get(opts, :mode, "generate")

    ResearchRender.CLI.run(repo_root, mode)
  end
end
