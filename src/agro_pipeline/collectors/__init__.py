from agro_pipeline.collectors import bcb, cepea, nasa_power
from agro_pipeline.collectors.base import Tarefa

TAREFAS: list[Tarefa] = cepea.TAREFAS + bcb.TAREFAS + nasa_power.TAREFAS
