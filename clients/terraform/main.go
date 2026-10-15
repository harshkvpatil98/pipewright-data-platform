// The Pipewright Terraform provider: run by Terraform, never by hand.
package main

import (
	"context"
	"flag"
	"log"

	"github.com/hashicorp/terraform-plugin-framework/providerserver"

	"github.com/harshkvpatil98/terraform-provider-pipewright/internal/provider"
)

// version is set when a release is built.
var version = "dev"

func main() {
	var debug bool
	flag.BoolVar(&debug, "debug", false, "run with support for debuggers such as delve")
	flag.Parse()
	err := providerserver.Serve(context.Background(), provider.New(version), providerserver.ServeOpts{
		Address: "registry.terraform.io/harshkvpatil98/pipewright",
		Debug:   debug,
	})
	if err != nil {
		log.Fatal(err.Error())
	}
}
