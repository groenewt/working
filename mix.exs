defmodule ResearchRender.MixProject do
  use Mix.Project

  def project do
    [
      app: :research_render,
      version: "0.1.0",
      elixir: "~> 1.18",
      start_permanent: Mix.env() == :prod,
      deps: deps()
    ]
  end

  def application do
    [
      extra_applications: [:crypto, :logger]
    ]
  end

  defp deps do
    [
      {:jason, "~> 1.4"},
      {:nimble_csv, "~> 1.3"},
      {:yaml_elixir, "~> 2.12"}
    ]
  end
end
