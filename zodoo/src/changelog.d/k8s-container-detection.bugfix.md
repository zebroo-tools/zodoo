zodoo erkennt Kubernetes-Pods jetzt als Container.

In einem Pod unter EKS (containerd, cgroup v2) gibt es kein `/.dockerenv`, und
`/proc/1/cgroup` enthält nur `0::/`. `_is_in_container()` lieferte dort False,
damit wurden `DBNAME` und die übrigen Einstellungen nicht aus der Umgebung
gelesen. Das Update beim Start brach mit `assert dbname` ab und der Pod zeigte
nur die Construction-Page. Zusätzlich gilt jetzt die Variable
`KUBERNETES_SERVICE_HOST`, die Kubernetes in jeden Pod setzt, als Hinweis auf
einen Container.
