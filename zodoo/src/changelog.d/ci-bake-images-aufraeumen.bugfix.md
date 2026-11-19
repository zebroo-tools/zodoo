CI only: the bake test now removes the images of its own run at the end
(`bake<run>-*`, `zpt19<run>-*`, `zptpgbr<run>-*`), also after a failed or
cancelled run. Before, every run left its images on the shared runner daemon
and the disk filled up within about a day. Images that still have a container
are kept with a warning.
