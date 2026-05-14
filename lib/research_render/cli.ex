defmodule ResearchRender.CLI do
  alias ResearchRender.Renderer

  def run(repo_root, "generate") do
    repo_root
    |> Renderer.new()
    |> Renderer.generate()
  end

  def run(repo_root, "install") do
    repo_root
    |> Renderer.new()
    |> Renderer.install()
  end

  def run(repo_root, "validate") do
    repo_root
    |> Renderer.new()
    |> Renderer.validate()
  end

  def run(repo_root, "all") do
    renderer = Renderer.new(repo_root)

    renderer
    |> Renderer.generate()
    |> Renderer.install()
    |> Renderer.validate()
  end

  def run(_repo_root, mode), do: abort!("unknown_mode #{mode}")

  def abort!(message) do
    IO.puts(:stderr, message)
    System.halt(1)
  end
end
