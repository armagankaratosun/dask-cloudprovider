import asyncio
import dask

from dask_cloudprovider.generic.vmcluster import (
    VMCluster,
    VMInterface,
    SchedulerMixin,
    WorkerMixin,
)

try:
    from openstack import connection
except ImportError as e:
    msg = (
        "Dask Cloud Provider OpenStack requirements are not installed.\n\n"
        "Please pip install as follows:\n\n"
        '  pip install "openstacksdk" ' 
    )
    raise ImportError(msg) from e

class OpenStackInstance(VMInterface):
    def __init__(
        self,
        cluster,
        config,
        region=None,
        size=None,
        image=None,
        docker_image=None,
        env_vars=None,
        extra_bootstrap=None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.instance = None
        self.cluster = cluster
        self.config = config
        self.region = region
        self.size = size
        self.image = image
        self.env_vars = env_vars
        self.bootstrap = True

    async def create_vm(self):
        conn = connection.Connection(
            region_name=self.region,
            auth_url=self.config['auth_url'],
            application_credential_id=self.config['application_credential_id'],
            application_credential_secret=self.config['application_credential_secret'],
            compute_api_version='2',
            identity_interface='public',
            auth_type="v3applicationcredential"
        )

        self.instance = conn.create_server(
            name=self.name,
            image=self.config['image_id'],  # Changed 'image_id' to 'image'
            flavor=self.size,               # Changed 'flavor_id' to 'flavor'
            key_name=self.config['keypair_name'],  # Add the keypair name here
            nics=[{'net-id': self.config['network_id']}],  # Changed from 'networks' to 'nics'
            userdata=self.cluster.render_process_cloud_init(self),
            security_groups=[self.config['security_group']],
        )

        # Wait for the instance to be up and running
        while self.instance.status.lower() != 'active':
            await asyncio.sleep(0.1)
            self.instance = conn.compute.get_server(self.instance.id)

        # Check configuration if floating IP should be created
        if self.config.get('create_floating_ip', False):  # Default is False if not specified
            try:
                # Create and associate floating IP
                external_network_id = self.config['external_network_id']
                floating_ip = conn.network.create_ip(floating_network_id=external_network_id)
                ports = conn.network.ports(device_id=self.instance.id)
                if ports:
                    conn.network.update_ip(floating_ip, port_id=ports[0].id)
                    ip_address = floating_ip.floating_ip_address
                    self.cluster._log(f"Floating IP {ip_address} associated with {self.instance.name}")
                else:
                    self.cluster._log("No network ports found to associate floating IP.")
            except Exception as e:
                self.cluster._log(f"Failed to create or associate floating IP: {str(e)}")
                ip_address = None  # Handle failure gracefully
        else:
            # If no floating IP is created, fetch the first available non-floating IP
            ip_address = next((addr.get('addr') for net in self.instance.addresses.values() for addr in net if addr.get('addr')), None)
 
        return ip_address

    async def destroy_vm(self):
        conn = connection.Connection(
            region_name=self.region,
            auth_url=self.config['auth_url'],
            application_credential_id=self.config['application_credential_id'],
            application_credential_secret=self.config['application_credential_secret'],
            compute_api_version='2',
            identity_interface='public',
            auth_type="v3applicationcredential"
        )

        # Handle floating IP disassociation and deletion if applicable
        if self.config.get('create_floating_ip', False):  # Checks if floating IPs were configured to be created
            try:
                # Retrieve all floating IPs associated with the instance
                floating_ips = conn.network.ips(port_id=self.instance.id)
                for ip in floating_ips:
                    # Disassociate and delete the floating IP
                    conn.network.update_ip(ip, port_id=None)
                    conn.network.delete_ip(ip.id)
                    self.cluster._log(f"Deleted floating IP {ip.floating_ip_address}")
            except Exception as e:
                self.cluster._log(f"Failed to clean up floating IPs for instance {self.name}: {str(e)}")
                return  # Exit if floating IP cleanup fails

        # Then, attempt to delete the instance
        try:
            instance = conn.compute.get_server(self.instance.id)
            if instance:
                await self.cluster.call_async(conn.compute.delete_server, instance.id)
                self.cluster._log(f"Terminated instance {self.name}")
            else:
                self.cluster._log(f"Instance {self.name} not found or already deleted.")
        except Exception as e:
            self.cluster._log(f"Failed to terminate instance {self.name}: {str(e)}") 

    async def start_vm(self):
        # Code to start the instance
        pass  # Placeholder to ensure correct indentation

    async def stop_vm(self):
        # Code to stop the instance
        pass  # Placeholder to ensure correct indentation

class OpenStackScheduler(SchedulerMixin, OpenStackInstance):
    """Scheduler running on an OpenStack Instance."""


class OpenStackWorker(WorkerMixin, OpenStackInstance):
    """Worker running on a OpenStack Instance."""


class OpenStackCluster(VMCluster):
    def __init__(
        self,
        region: str = None,
        size: str = None,
        image: str = None,
        debug: bool = False,
        **kwargs,
    ):
        self.config = dask.config.get("cloudprovider.openstack", {})
        self.scheduler_class = OpenStackScheduler
        self.worker_class = OpenStackWorker
        self.debug = debug
        self.options = {
            "cluster": self,
            "config": self.config,
            "region": region if region is not None else self.config.get("region"),
            "size": size if size is not None else self.config.get("size"),
            "image": image if image is not None else self.config.get("image"),
        }
        self.scheduler_options = {**self.options}
        self.worker_options = {**self.options}
        super().__init__(debug=debug, **kwargs)