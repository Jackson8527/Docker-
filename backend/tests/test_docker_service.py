from app.services import docker


def test_extract_error():
    assert "no such" in docker.extract_error(Exception("404 no such container"))


def test_extract_error_empty():
    assert docker.extract_error(Exception("")) == "Unknown docker error"


def test_dataclass_fields():
    ci = docker.ContainerInfo(id="x", name="n", image="img", state="running",
                              status="up", ports="", created="")
    assert ci.id == "x" and ci.state == "running"