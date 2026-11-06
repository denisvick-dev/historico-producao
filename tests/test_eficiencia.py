import pandas as pd

from components.eficiencia import calcular_eficiencia


def test_limites_e_soma_mensal():
    frame = pd.DataFrame({
        "technician": ["A"] * 7,
        "reference_date": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01", "2024-05-01", "2024-05-01", "2024-06-01"]),
        "points": [299.99, 300, 350, 375, 200, 200, 349.99],
    })
    detalhes, resumo = calcular_eficiencia(frame)
    assert detalhes["Faixa"].tolist() == ["Faixa 1", "Faixa 2", "Faixa 3", "Faixa 4", "Faixa 5", "Faixa 2"]
    assert detalhes.iloc[4]["Pontos"] == 400
    assert resumo.iloc[0]["Faixa mais frequente"] == "Faixa 2"
    assert resumo.iloc[0]["Meses com registros"] == 6


def test_empate_e_meses_sem_registro():
    frame = pd.DataFrame({"technician": ["A", "A", "B"], "period": pd.to_datetime(["2024-01-01", "2024-03-01", "2024-03-01"]), "points": [0, 400, 374.99]})
    _, resumo = calcular_eficiencia(frame)
    assert resumo.iloc[0]["Faixa mais frequente"] == "Faixa 1 / Faixa 5"
    assert resumo.iloc[0]["Meses com registros"] == 2
    assert resumo.iloc[1]["Faixa mais frequente"] == "Faixa 3"


def test_sem_dados_validos():
    detalhes, resumo = calcular_eficiencia(pd.DataFrame())
    assert detalhes.empty and resumo.empty
