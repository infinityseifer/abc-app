import altair as alt
import pandas as pd

def bar_count(df: pd.DataFrame, col: str, title: str):
    data = df.groupby(col).size().reset_index(name="count")
    return alt.Chart(data).mark_bar().encode(
        x=alt.X("count:Q", title="Incidents"),
        y=alt.Y(f"{col}:N", sort='-x', title=title),
        tooltip=[col, "count"]
    )

def stacked_antecedent_behavior(df: pd.DataFrame):
    ab = df.groupby(["antecedent","behavior"]).size().reset_index(name="count")
    return alt.Chart(ab).mark_bar().encode(
        x=alt.X("antecedent:N", title="Antecedent"),
        y=alt.Y("count:Q", title="Incidents"),
        color="behavior:N",
        tooltip=["antecedent","behavior","count"]
    )
